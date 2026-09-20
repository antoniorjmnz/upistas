from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.importes import normaliza_iban, parse_fecha, parse_fecha_letras, parse_importe
from upistas.dominio.notas import clasificar, normalizar

INVISIBLE = r"[\u200b\ufeff]*"
DIGITO = rf"\d{INVISIBLE}"
NUMERO = rf"[+-]?{INVISIBLE}(?:{DIGITO})+(?:(?:[.,]|[ \u00a0]){INVISIBLE}(?:{DIGITO}){{3}})*[.,]{INVISIBLE}(?:{DIGITO}){{2}}(?!\d)"
LETRA = r"[^\W\d_]"
FECHA = (r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}"
         rf"|\d{{1,2}}\s+de\s+{LETRA}+\s+de\s+\d{{4}}")
CAMPOS = ("numero_factura", "nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total")
SEPARADOR = r"[\s.:=#·…]*"

# Divisa: los importes se leen en la moneda que sea y la divisa se guarda como campo propio; sin marca, euros.
MONEDA = r"(EUR|€|EUROS?|USD|JPY|GBP|CHF|BRL|MXN|CAD|AUD|US\$|MX\$|R\$|\$|¥|£|FR\.?)"
# Con la moneda delante también vale un importe sin decimales con miles («¥ 850,000»: el yen no los tiene).
ENTERO_MILES = rf"(?:{DIGITO}){{1,3}}(?:[.,]{INVISIBLE}(?:{DIGITO}){{3}})+(?![.,]?\d)"
IMPORTE = rf"(?:{MONEDA}[ \t]*({NUMERO}|{ENTERO_MILES})|({NUMERO}))"
CODIGO_TRAS = r"(?:[ \t]+(EUR|USD|JPY|GBP|CHF|BRL|MXN|CAD|AUD)\b)?"
SIMBOLO_A_CODIGO = {"€": "EUR", "EURO": "EUR", "EUROS": "EUR", "$": "USD", "¥": "JPY", "£": "GBP",
                    "FR": "CHF", "FR.": "CHF", "R$": "BRL", "MX$": "MXN", "US$": "USD"}
ETIQUETA_DIVISA = (r"(?:DIVISA\s+DE\s+FACTURACI[ÓO]N|BILLING\s+CURRENCY|RECHNUNGSW[ÄA]HRUNG|"
                   r"MOEDA\s+DE\s+FATURA[ÇC][ÃA]O|MONEDA\s+DE\s+FACTURACI[ÓO]N)\s*[:.]?\s*\(?\s*([A-Z]{3})\b")

ETIQUETA_IVA = (r"(?<!\w)(?:I[ \t.]*V[ \t.]*A\.?|V[ \t.]*A[ \t.]*T\.?|T[ \t.]*V[ \t.]*A\.?|"
                r"M[ \t.]*W[ \t.]*S[ \t.]*T\.?)(?!\w)")
ETIQUETA_BASE = (r"(?:{base}(?:\s+IMPONIBLE|\s+IMPOSABLE)?|{subtotal}|{sous}\s*-\s*{total}|{sous}\s+{total}|"
                 r"{zwischen}|{imponibile}|{valor}\s+{base2}|{base3}\s+{imposable})").format(
    base=r"(?<!\w)B[ \t]*A[ \t]*S[ \t]*E(?!\w)", subtotal=r"(?<!\w)S[ \t]*U[ \t]*B[ \t]*T[ \t]*O[ \t]*T[ \t]*A[ \t]*L(?!\w)",
    sous=r"(?<!\w)S[ \t]*O[ \t]*U[ \t]*S", total=r"T[ \t]*O[ \t]*T[ \t]*A[ \t]*L(?!\w)",
    zwischen=r"(?<!\w)Z[ \t]*W[ \t]*I[ \t]*S[ \t]*C[ \t]*H[ \t]*E[ \t]*N[ \t]*S[ \t]*U[ \t]*M[ \t]*M[ \t]*E(?!\w)",
    imponibile=r"(?<!\w)I[ \t]*M[ \t]*P[ \t]*O[ \t]*N[ \t]*I[ \t]*B[ \t]*I[ \t]*L[ \t]*E(?!\w)",
    valor=r"(?<!\w)V[ \t]*A[ \t]*L[ \t]*O[ \t]*R", base2=r"B[ \t]*A[ \t]*S[ \t]*E(?!\w)",
    base3=r"(?<!\w)B[ \t]*A[ \t]*S[ \t]*E", imposable=r"I[ \t]*M[ \t]*P[ \t]*O[ \t]*S[ \t]*A[ \t]*B[ \t]*L[ \t]*E(?!\w)")
# TOTAL/TOTALE/GESAMT: con guion delante no vale, para que «Sous-total» no cuente como total.
ETIQUETA_TOTAL = (r"(?:(?<![\w-])T[ \t]*O[ \t]*T[ \t]*A[ \t]*L(?:E[ \t]*)?(?!\w)"
                  r"|(?<!\w)G[ \t]*E[ \t]*S[ \t]*A[ \t]*M[ \t]*T(?!\w))")
ETIQUETA_FECHA = (r"(?:F[ \t]*E[ \t]*C[ \t]*H[ \t]*A(?:\s+(?:DE\s+)?EMISI[ÓO]N)?|ISSUE\s+DATE|INVOICE\s+DATE|"
                  r"DATE\s+D['’][ÉE]MISSION|DATA\s+D['’]EMISSI[ÓO]|DATA\s+DE\s+EMISS[ÃA]O|"
                  r"DATA\s+DI\s+EMISSIONE|AUSSTELLUNGSDATUM|RECHNUNGSDATUM)")
ETIQUETA_NIF = (r"(?:NIF|CIF|TAX\s+ID|UST-?ID(?:NUMMER)?|N[°ºo]?\s*TVA|P\.?\s*IVA|"
                r"VAT\s*(?:ID|NUMBER|N[°ºo.]?)|CNPJ)\b")
ETIQUETA_IBAN = r"(?:IBAN|CONTA|KONTO|COMPTE|CONTO)\b"
def coste_de(paginas: list[dict]) -> dict | None:
    """Lo que costó leer: cada página escaneada pasa por el OCR y, si hizo falta, por la visión (que suma tokens)."""
    modelos = []
    for pagina in paginas:
        ruta = str(pagina.get("route", ""))
        if ruta.endswith("ocr") or ruta == "vision_llm":
            modelos.append(pagina.get("modelo_ocr") or (pagina.get("model") if ruta.endswith("ocr") else None) or "ocr")
        if ruta == "vision_llm" and pagina.get("model"):
            modelos.append(pagina["model"])
    if not modelos:
        return None
    return {
        "modelo": " + ".join(dict.fromkeys(modelos)),
        "tokens_in": sum(p.get("tokens_in") or 0 for p in paginas),
        "tokens_out": sum(p.get("tokens_out") or 0 for p in paginas),
    }

FECHA_INVALIDA = "fecha inválida"  # marca interna: el texto es una fecha en cifras que no existe en el calendario


def etiqueta(palabra: str) -> str:
    return r"(?<!\w)" + r"[ \t]*".join(palabra) + r"(?!\w)"


def separar_notas(texto: str) -> tuple[str, list[str]]:
    datos, notas, actual = [], [], []
    tras_total = final = False
    for linea in texto.splitlines():
        normal = normalizar(linea)
        categorias = clasificar(linea)
        dato = bool(re.match(r"^(?:nif|cif|iban|cuenta|factura|invoice|facture|fattura|fatura|rechnung|"
                             r"fecha|data|date|ausstellungsdatum|pedido|ref|po|purchase order|bon de commande|"
                             r"bestellung|ordine|encomenda|comanda|base|subtotal|sous-total|zwischensumme|"
                             r"imponibile|valor base|iva|vat|tva|mwst|total|totale|gesamt|importe|cuota|"
                             r"cliente|client|bill to|factur|faturar|rechnungsempf|tax id|ust|proveedor|"
                             r"divisa|moeda|billing currency|rechnungsw)\b", normal))
        inicio = bool(re.match(r"^(?:notas?|observaci(?:on|ones)|aviso|comentario|instrucciones?|condiciones de pago|"
                               r"payment terms|conditions de paiement|condicoes de pagamento|condicions de pagament|"
                               r"termini di pagamento|zahlungsbedingungen|zahlungsziel)\b", normal))
        afirmacion = bool(re.search(r"\b(?:pedido|proveedor)\b.{0,50}(?:anulad|cancelad|en revision)|\b(?:iban|cuenta de abono|cuenta bancaria)\b.{0,50}\b(?:no coincid|no coincident|distint)", normal))
        inicio = inicio or any(c in categorias for c in ("pide_saltar_regla", "dirigida_al_sistema")) or afirmacion or (categorias != ("otra",) and not dato)
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


def _codigo_divisa(marca: str) -> str:
    """'€'/'EUR' → 'EUR', '$' → 'USD', 'Fr' → 'CHF'… Cadena vacía si no hay marca."""
    marca = marca.strip().upper()
    return SIMBOLO_A_CODIGO.get(marca, marca)


def extraer_campos(file_id: str, paginas: list[dict], documento: dict | None = None) -> FacturaExtraida:
    candidatos = defaultdict(list)
    errores = []
    notas = []
    divisas = {}  # código → texto donde se vio: junto a un importe o en la línea de «Divisa de facturación»

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
            if re.search(r"\b(?:CLIENTE|CLIENT|DESTINATARIO|FACTURAR\s+A|FACTUR[ÉE]?\s+[ÀA]|"
                         r"FATURAR\s+A|FATURADO\s+A|BILL\s+TO|RECHNUNGSEMPF[ÄA]NGER|FATTURATO\s+A)\b", linea, re.I):
                cliente = True
            if re.search(r"\b(?:PROVEEDOR|EMISOR|FORNECEDOR|FOURNISSEUR|LIEFERANT|FORNITORE|EMITTENT)\b", linea, re.I):
                cliente = False
            if not cliente:
                for m in re.finditer(r"\b(?:[A-Z]\s*\d{7}[A-Z0-9]|\d{8}[A-Z])\b", linea, re.I):
                    guardar("nif", re.sub(r"\s", "", m[0]).upper(), linea)
                # NIF extranjero o con formato raro, pero etiquetado: «USt-ID: DE812345678», «N° TVA: FR40…»,
                # «NIF: 12.345.678/0001-95»… Se lee para que el motivo diga «no está en el maestro» y no «no leído».
                for m in re.finditer(ETIQUETA_NIF + SEPARADOR + r"([A-Z0-9][A-Z0-9.\-/]{4,20})", linea, re.I):
                    nif = re.sub(r"[\s\u200b\ufeff]", "", m[1]).upper()
                    if not re.fullmatch(r"[A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z]", nif):
                        guardar("nif", nif, linea)

        for m in re.finditer(r"\bE[\s\u200b\ufeff]*S(?:[\s.\-\u200b\ufeff]*\d){22}(?!\d)", texto, re.I):
            guardar("iban", normaliza_iban(m[0]), m[0])
        # IBAN de fuera de España (DE89…, FR76…, GB29…, JP01…): etiquetado y dentro de la misma línea.
        for m in re.finditer(ETIQUETA_IBAN + SEPARADOR + r"([A-Z]{2}[ \t.\-]*\d{2}(?:[ \t.\-]*[A-Z0-9]){10,30})", texto):
            iban = normaliza_iban(m[1])
            if iban and not iban.startswith("ES"):
                guardar("iban", iban, m[0])
        for m in re.finditer(r"\bP\s*O\s*-?\s*(\d{4})\s*-\s*(\d{3,5})\b", texto, re.I):
            guardar("pedido", f"PO-{m[1]}-{m[2]}", m[0])
        for m in re.finditer(
            r"^[ \t]*(?:(?:N[º°o.]?|N[ÚU]MERO|REF(?:ERENCIA)?)[ \t]*(?:DE[ \t]+)?)?"
            + rf"(?:{etiqueta('FACTURA')}|{etiqueta('INVOICE')}|{etiqueta('FACTURE')}"
            + rf"|{etiqueta('FATTURA')}|{etiqueta('FATURA')}|{etiqueta('RECHNUNG')})"
            + r"[ \t]*(?:N[\wº°.]*[ \t]*)?[:#]?[ \t]*([A-Z0-9][A-Z0-9/\-]*\d[A-Z0-9/\-]*)(?=\s|$)",
            texto, re.I | re.M,
        ):
            guardar("numero_factura", m[1].upper(), m[0])
        for m in re.finditer(
            etiqueta("FECHA") + r"(?:\s+(?:DE\s+)?(?:EMISI[ÓO]N|FACTURA))?\s*[:#]?\s*(" + FECHA + r")",
            texto, re.I,
        ):
            fecha = parse_fecha(m[1])
            # Una fecha en cifras que no existe (31/02/2026) se leyó bien; un mes escrito que no se reconoce, no.
            invalida = fecha is None and not re.search(r"[a-z]", m[1], re.I)
            guardar("fecha", FECHA_INVALIDA if invalida else fecha.isoformat() if fecha else None, m[0])
        # Fechas con etiqueta en otro idioma o escritas en letra («dos de enero de dos mil veintiséis»):
        # solo se guarda lo que se entiende; lo demás queda como no leído, como hasta ahora.
        for m in re.finditer(ETIQUETA_FECHA + SEPARADOR + r"([^\n]{3,90})", texto, re.I):
            resto = m[1].strip().rstrip(".")
            fecha = parse_fecha(resto) or parse_fecha_letras(resto)
            if fecha:
                guardar("fecha", fecha.isoformat(), m[0])

        patrones = {
            "base": rf"(?:{ETIQUETA_BASE}){SEPARADOR}{IMPORTE}{CODIGO_TRAS}",
            "iva": rf"{ETIQUETA_IVA}{SEPARADOR}(?:\(?\s*\d{{1,2}}(?:[.,]\d+)?\s*%\s*\)?{SEPARADOR})?{IMPORTE}(?!\s*%){CODIGO_TRAS}",
            "total": rf"{ETIQUETA_TOTAL}(?:\s+(?:FACTURA|A\s+PAGAR))?{SEPARADOR}{IMPORTE}{CODIGO_TRAS}",
        }
        for m in re.finditer(rf"{ETIQUETA_IVA}{SEPARADOR}\(?\s*(\d{{1,2}}(?:[.,]\d+)?)\s*%", texto, re.I):
            guardar("iva_pct", m[1].replace(",", "."), m[0])
        for campo, patron in patrones.items():
            for m in re.finditer(patron, texto, re.I):
                divisa = _codigo_divisa(m[1] or "") or _codigo_divisa(m[4] or "")
                if divisa:
                    divisas.setdefault(divisa, m[0])
                valor = parse_importe(m[2] or m[3])
                guardar(campo, float(valor) if valor is not None else None, m[0])
        for m in re.finditer(ETIQUETA_DIVISA, texto, re.I):
            divisas.setdefault(m[1].upper(), m[0])

    # La divisa es un dato más: sin marca o con €/EUR, euros. Dos monedas distintas del euro en la misma
    # factura no se pueden interpretar; se avisa y la factura acaba en revisión.
    otras = sorted(d for d in divisas if d != "EUR")
    if len(otras) > 1:
        errores.append(f"Importes en {'dos' if len(otras) == 2 else 'varias'} divisas: {', '.join(otras[:-1])} y {otras[-1]}")
    campos = {"divisa": {
        "valor": otras[0] if len(otras) == 1 else "EUR" if not otras else None,
        "confianza": 0.0 if len(otras) > 1 else 1.0,
        "fuente": "\n".join(dict.fromkeys(divisas.values())) or None,
    }}
    for nombre in CAMPOS:
        encontrados = candidatos[nombre]
        valores = {v for v, _ in encontrados}
        # Una fecha inválida leída con seguridad va sin valor pero con confianza plena: no es un fallo de
        # lectura (el campo queda en `ausentes`, no en `no_leidos`) y la juzga la regla de la fecha.
        invalida = valores == {FECHA_INVALIDA}
        valor = next(iter(valores)) if len(valores) == 1 and None not in valores and not invalida else None
        if len(valores) > 1:
            errores.append(f"Valores contradictorios para {nombre}")
        elif encontrados and valor is None and not invalida:
            errores.append(f"Valor inválido para {nombre}")
        campos[nombre] = {
            "valor": valor,
            "confianza": 1.0 if valor is not None or invalida else 0.0,
            "fuente": "\n".join(dict.fromkeys(raw for _, raw in encontrados)) or None,
        }

    return FacturaExtraida.model_validate({
        "file_id": file_id,
        "metodo": _metodo(paginas),
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
        "coste": coste_de(paginas),
    })


def _metodo(paginas: list[dict]) -> str:
    """Quién leyó el documento, según la ruta real de cada página: visión > OCR > texto nativo."""
    rutas = {str(p.get("route", "")) for p in paginas}
    if "vision_llm" in rutas:
        return "vision_llm"
    if any(ruta.endswith("ocr") for ruta in rutas):
        return "ocr_determinista"
    return "texto_determinista"


def _coste(paginas: list[dict]) -> dict | None:
    """Qué modelo leyó el documento, si se usó OCR. Sale de la traza de la página, no del nombre del adaptador."""
    modelo = next((p.get("model") for p in paginas if str(p.get("route", "")).endswith("ocr") and p.get("model")), None)
    return {"modelo": modelo} if modelo else None
