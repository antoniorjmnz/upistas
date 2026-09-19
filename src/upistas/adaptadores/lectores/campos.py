from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.importes import normaliza_iban, parse_fecha, parse_importe
from upistas.dominio.notas import clasificar, normalizar

INVISIBLE = r"[\u200b\ufeff]*"
DIGITO = rf"\d{INVISIBLE}"
NUMERO = rf"[+-]?{INVISIBLE}(?:{DIGITO})+(?:(?:[.,]|[ \u00a0]){INVISIBLE}(?:{DIGITO}){{3}})*[.,]{INVISIBLE}(?:{DIGITO}){{2}}(?!\d)"
MONEDA = r"(?:(?:EUR|€)[ \t]*)?"
FECHA = r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{1,2} de [a-z]+ de \d{4}"
CAMPOS = ("numero_factura", "nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total")
SEPARADOR = r"[\s.:=#·…]*"
ETIQUETA_IVA = r"(?<!\w)I[ \t.]*V[ \t.]*A\.?(?!\w)"


def etiqueta(palabra: str) -> str:
    return r"(?<!\w)" + r"[ \t]*".join(palabra) + r"(?!\w)"


def separar_notas(texto: str) -> tuple[str, list[str]]:
    datos, notas, actual = [], [], []
    tras_total = final = False
    for linea in texto.splitlines():
        normal = normalizar(linea)
        categorias = clasificar(linea)
        dato = bool(re.match(r"^(?:nif|cif|iban|cuenta|factura|invoice|fecha|pedido|ref|po|base|subtotal|iva|total|importe|cuota|cliente|bill to|proveedor)\b", normal))
        inicio = bool(re.match(r"^(?:notas?|observaci(?:on|ones)|aviso|comentario|instrucciones?|condiciones de pago)\b", normal))
        afirmacion = bool(re.search(r"\b(?:pedido|proveedor)\b.{0,50}(?:anulad|cancelad|en revision)|\biban\b.{0,50}\bno coincide", normal))
        inicio = inicio or "pide_saltar_regla" in categorias or afirmacion or (categorias != ("otra",) and not dato)
        if final or inicio or (actual and not dato):
            final = final or (tras_total and inicio)
            actual.append(linea)
        else:
            if actual:
                notas.append("\n".join(actual).strip())
                actual = []
            datos.append(linea)
            tras_total = tras_total or bool(re.match(r"^total\b", normal))
    if actual:
        notas.append("\n".join(actual).strip())
    return "\n".join(datos), [n for n in notas if n]


def extraer_campos(file_id: str, paginas: list[dict], documento: dict | None = None) -> FacturaExtraida:
    candidatos = defaultdict(list)
    errores = []
    notas = []

    def guardar(campo, valor, original):
        candidatos[campo].append((valor, original))

    for pagina in paginas:
        if pagina.get("error"):
            errores.append(f"Página {pagina['page']}: {pagina['error']}")
        original = pagina.get("text", "")
        if len(original) > 2_000_000:
            errores.append(f"Página {pagina['page']}: texto demasiado extenso")
            continue
        texto, encontradas = separar_notas(original)
        for nota in encontradas:
            if len(nota) > 16384:
                errores.append("Nota demasiado extensa para procesarla automáticamente")
            notas.append({"texto": nota[:16385], "categorias": list(clasificar(nota[:16385]))})
        texto = texto.replace("\u2013", "-").replace("\u2014", "-")
        cliente = False
        for linea in texto.splitlines():
            if re.search(r"\b(?:CLIENTE|DESTINATARIO|FACTURAR\s+A|BILL\s+TO)\b", linea, re.I):
                cliente = True
            if re.search(r"\b(?:PROVEEDOR|EMISOR)\b", linea, re.I):
                cliente = False
            if not cliente:
                for m in re.finditer(r"\b(?:[A-Z]\s*\d{7}[A-Z0-9]|\d{8}[A-Z])\b", linea, re.I):
                    guardar("nif", re.sub(r"\s", "", m[0]).upper(), linea)

        for m in re.finditer(r"\bE[\s\u200b\ufeff]*S(?:[\s.\-\u200b\ufeff]*\d){22}(?!\d)", texto, re.I):
            guardar("iban", normaliza_iban(m[0]), m[0])
        for m in re.finditer(r"\bP\s*O\s*-?\s*(\d{4})\s*-\s*(\d{3,5})\b", texto, re.I):
            guardar("pedido", f"PO-{m[1]}-{m[2]}", m[0])
        for m in re.finditer(
            r"^[ \t]*(?:(?:N[º°o.]?|N[ÚU]MERO|REF(?:ERENCIA)?)[ \t]*(?:DE[ \t]+)?)?"
            + rf"(?:{etiqueta('FACTURA')}|{etiqueta('INVOICE')})"
            + r"[ \t]*(?:N[º°o.]?[ \t]*)?[:#]?[ \t]*([A-Z0-9][A-Z0-9/\-]*\d[A-Z0-9/\-]*)(?=\s|$)",
            texto, re.I | re.M,
        ):
            guardar("numero_factura", m[1].upper(), m[0])
        for m in re.finditer(
            etiqueta("FECHA") + r"(?:\s+(?:DE\s+)?(?:EMISI[ÓO]N|FACTURA))?\s*[:#]?\s*(" + FECHA + r")",
            texto, re.I,
        ):
            fecha = parse_fecha(m[1])
            guardar("fecha", fecha.isoformat() if fecha else None, m[0])

        patrones = {
            "base": rf"(?:{etiqueta('BASE')}(?:\s+IMPONIBLE)?|{etiqueta('SUBTOTAL')}){SEPARADOR}{MONEDA}({NUMERO})",
            "iva_pct": rf"{ETIQUETA_IVA}{SEPARADOR}\(?\s*(\d{{1,2}}(?:[.,]\d+)?)\s*%",
            "iva": rf"{ETIQUETA_IVA}{SEPARADOR}(?:\(?\s*\d{{1,2}}(?:[.,]\d+)?\s*%\s*\)?{SEPARADOR})?{MONEDA}({NUMERO})(?!\s*%)",
            "total": rf"{etiqueta('TOTAL')}(?:\s+(?:FACTURA|A\s+PAGAR))?{SEPARADOR}{MONEDA}({NUMERO})",
        }
        for campo, patron in patrones.items():
            for m in re.finditer(patron, texto, re.I):
                valor = parse_importe(m[1]) if campo != "iva_pct" else m[1].replace(",", ".")
                guardar(campo, float(valor) if valor is not None else None, m[0])

    campos = {}
    for nombre in CAMPOS:
        encontrados = candidatos[nombre]
        valores = {v for v, _ in encontrados}
        valor = next(iter(valores)) if len(valores) == 1 and None not in valores else None
        if len(valores) > 1:
            errores.append(f"Valores contradictorios para {nombre}")
        elif encontrados and valor is None:
            errores.append(f"Valor inválido para {nombre}")
        campos[nombre] = {
            "valor": valor,
            "confianza": 1.0 if valor is not None else 0.0,
            "fuente": "\n".join(dict.fromkeys(raw for _, raw in encontrados)) or None,
        }

    return FacturaExtraida.model_validate({
        "file_id": file_id,
        "metodo": "texto_determinista",
        "lector": "pdf_unificado",
        "documento": documento or {
            "sha256": hashlib.sha256("\n".join(p.get("text", "") for p in paginas).encode()).hexdigest(),
            "tipo": "otro",
            "paginas": len(paginas),
        },
        "campos": campos,
        "notas": notas,
        "checks": {},
        "errores": errores,
        "coste": {"modelo": "fal-ai/got-ocr/v2"} if any(p["route"] == "fal_ocr" for p in paginas) else None,
    })
