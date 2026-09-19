"""Lector de PDFs con capa de texto (471 de 500 en La Caja). Sin IA: rápido, gratis y auditable.

Las facturas vienen en unas diez plantillas: etiquetas distintas para lo mismo, importes en
formato español (2.489,99) e inglés (EUR 1498.30), fechas numéricas o "15 de enero de 2026".
Cada campo se busca por su etiqueta; si solo se encuentra sin etiqueta, la confianza baja.
Todo lo que no es un dato de la factura (condiciones, avisos, instrucciones) sale como nota.
"""
from __future__ import annotations

import re
import time
from decimal import Decimal

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio import notas as notas_dom
from upistas.dominio.importes import normaliza_iban, parse_fecha, parse_importe
from upistas.puertos import DocumentoInspeccionado, LecturaFallida

NUM = r"-?\d[\d.,]*\d|\d"
FLAGS = re.IGNORECASE

# Etiqueta → valor. El orden importa: primero la más específica.
PATRONES = {
    "numero_factura": [
        r"factura simplificada n[ºo°]?\s*:?\s*(\S+)",
        r"n[ºo°]\s*de\s*factura\s*:?\s*(\S+)",
        r"factura\s*n[ºo°]\s*:?\s*(\S+)",
        r"ref\.?\s*factura\s*:?\s*(\S+)",
        r"invoice\s*#\s*(\S+)",
        r"factura\s*:\s*(\S+)",
    ],
    "nif": [r"\bNIF\s*:?\s*([A-Z]\d{7}[A-Z0-9])\b"],
    "cliente_cif": [r"\bCIF\s*:?\s*([A-Z]\d{7}[A-Z0-9])\b"],
    "pedido": [r"(?:ref\.?\s*pedido|su pedido|pedido cliente|pedido asociado|pedido|\bPO)\s*:?\s*(PO-\d{4}-\d{4})"],
    "fecha": [r"fecha(?:\s+de\s+emisi[oó]n|\s+factura)?\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})"],
    "base": [rf"(?:base imponible|importe base|subtotal|base)\s*[.:]*\s*(?:eur\s*)?({NUM})"],
    "iva_pct": [r"i\.?v\.?a\.?\s*\(\s*(\d+(?:[.,]\d+)?)\s*%\s*\)"],
    "iva": [rf"(?:cuota iva|i\.?v\.?a\.?)\s*\([^)]*\)\s*[.:]*\s*(?:eur\s*)?({NUM})"],
    "total": [rf"(?<![a-z])(?:total a pagar|importe total|total factura|total)\s*[.:]*\s*(?:eur\s*)?({NUM})"],
}
IBAN = re.compile(r"IBAN\)?\s*:?\s*([A-Z]{2}\d{2}[\d \u200b-\u200f\u2060\ufeff\u00ad]{18,40})")
PEDIDO_SUELTO = re.compile(r"\bPO-\d{4}-\d{4}\b")
EMPRESA = re.compile(r"\b(S\.?\s?L\.?\s?U?\.?|S\.?\s?A\.?|S\.?\s?C\.?|S\.?\s?Coop\.?)(?=\s|$|\.)", FLAGS)
EMISOR = re.compile(r"emisor\s*:\s*(.+?)\s*(?:·|\||$)", FLAGS | re.M)

LINEA_ITEM = [
    # "Servicio mensual ....... 2.489,99" · "- Material (1 ud): EUR 1498.30" · "Transporte urgente (1) — 458,04 €" · "Consumibles  x1  ...  96,17 €"
    re.compile(rf"^\s*-?\s*(?P<c>[^\d].*?)\s*(?:\(\s*\d+(?:\s*ud)?\s*\)|x\s*\d+)?\s*(?:\.{{3,}}|—|:)\s*(?:eur\s*)?(?P<n>{NUM})\s*€?\s*$", FLAGS),
    # tabla "Concepto   Uds   Importe": "Instalación    1    230,13"
    re.compile(rf"^\s*(?P<c>[^\d].*?)\s{{2,}}(?P<q>\d+)\s{{2,}}(?P<n>{NUM})\s*$", FLAGS),
    # "MATERIAL DE OFICINA                       416,89"
    re.compile(rf"^\s*(?P<c>[^\d].*?[^\d.:])\s{{2,}}(?P<n>{NUM})\s*€?\s*$", FLAGS),
]
ETIQUETAS_TOTALES = re.compile(r"^\s*(base|subtotal|importe base|cuota|i\.?v\.?a|total|importe total)", FLAGS)

# Líneas que son plantilla, no datos ni notas.
RELLENO = [
    re.compile(p, FLAGS)
    for p in (
        r"^factura$", r"documento generado por el sistema", r"^detalle de servicios", r"^concepto\s+uds\s+importe",
        r"^-{4,}$", r"^p[áa]gina \d+", r"^(bill to|cliente|facturar a|destinatario)\s*:", r"^paseo de la castellana",
        r"^[A-ZÁÉÍÓÚ ]{3,}$",  # "VALENCIA", "SEVILLA" sueltos
        r"^[\wáéíóúñ ]{3,30} · españa$",  # "Valencia · España"
    )
]
LINEA_CON_DATO = [re.compile(p, FLAGS) for p in (
    r"\b(NIF|CIF)\s*:?\s*[A-Z]\d{7}", r"IBAN\)?\s*:?\s*[A-Z]{2}\d{2}", r"PO-\d{4}-\d{4}",
    r"fecha[^:]*:\s*\d", r"fecha[^:]*:\s*\d{1,2} de", r"(factura( simplificada)?|invoice)\s*(n[ºo°]|#|:)", r"^emisor\s*:",
    rf"^(base|subtotal|importe base|cuota|i\.?v\.?a|total|importe total)\b.*({NUM})\s*€?\s*$",
)]
FRASES_RELLENO = [
    re.compile(p, FLAGS)
    for p in (
        r"condiciones de pago:\s*30 dias fecha factura\.?", r"documento emitido conforme al rd 1619/2012\.?",
        r"domicilio social y datos registrales a disposicion del cliente\.?",
    )
]
LIMITE = Decimal("0.01")


class LectorPdfTexto:
    nombre = "pdf_texto"
    metodo = "texto_determinista"

    def acepta(self, doc: DocumentoInspeccionado) -> bool:
        return doc.tipo == "texto"

    def leer(self, doc: DocumentoInspeccionado) -> FacturaExtraida:
        t0 = time.perf_counter()
        crudo = "\n".join(doc.texto_por_pagina)
        texto = re.sub(r"[\u200b-\u200f\u2060\ufeff\u00ad]", "", crudo)
        campos = {nombre: self._campo(texto, patrones) for nombre, patrones in PATRONES.items()}
        campos["iban"] = self._iban(texto)  # sobre el texto limpio: los invisibles ya están en las alertas
        campos["proveedor_nombre"] = self._proveedor(texto)
        if campos["pedido"]["valor"] is None:
            sueltos = sorted(set(PEDIDO_SUELTO.findall(texto)))
            if len(sueltos) == 1:
                campos["pedido"] = {"valor": sueltos[0], "confianza": 0.85, "fuente": sueltos[0]}
            elif sueltos:
                campos["pedido"] = {"valor": sueltos[0], "confianza": 0.4, "fuente": " / ".join(sueltos)}
        campos["fecha"] = self._fecha(campos["fecha"])

        lineas, notas_de_lineas = self._lineas(texto)
        self._deducir_importes(campos, lineas)
        notas = self._notas(texto) + notas_de_lineas

        presentes = sum(1 for k in ("nif", "iban", "pedido", "fecha", "base", "total") if campos[k]["valor"] is not None)
        if presentes < 3:
            raise LecturaFallida(f"solo se reconocen {presentes} datos: plantilla desconocida o no es una factura")

        for nombre, campo in campos.items():
            if campo.get("fuente"):
                campo["pagina"] = self._pagina(doc, campo["fuente"])

        extraida = {
            "file_id": doc.file_id,
            "metodo": self.metodo,
            "lector": self.nombre,
            "documento": {"sha256": doc.sha256, "tipo": doc.tipo, "paginas": doc.paginas, "bytes": doc.bytes, "alertas": list(doc.alertas)},
            "campos": campos,
            "lineas": [{"concepto": c, "importe": float(n)} for c, n in lineas],
            "notas": [{"texto": n.texto, "categorias": list(n.categorias)} for n in notas],
            "checks": self._checks(campos, lineas),
            "coste": {"segundos": round(time.perf_counter() - t0, 4)},
        }
        return FacturaExtraida.model_validate(extraida)

    # --- campos ------------------------------------------------------------------------------

    @staticmethod
    def _campo(texto: str, patrones: list[str]) -> dict:
        for patron in patrones:
            encontrados = list(re.finditer(patron, texto, FLAGS))
            if not encontrados:
                continue
            m = encontrados[-1] if patron.startswith("(?<![a-z])(?:total") else encontrados[0]
            valor = m.group(1).strip().rstrip("·.,;")
            return {"valor": valor, "confianza": 1.0, "fuente": " ".join(m.group(0).split())}
        return {"valor": None, "confianza": 1.0}  # el texto se lee entero: si no está, es que no está

    @staticmethod
    def _iban(crudo: str) -> dict:
        m = IBAN.search(crudo)
        if not m:
            return {"valor": None, "confianza": 1.0}
        limpio = normaliza_iban(re.sub(r"[\u200b-\u200f\u2060\ufeff\u00ad]", "", m.group(1)))
        confianza = 1.0 if len(limpio) == 24 and limpio.startswith("ES") else 0.7
        return {"valor": limpio, "confianza": confianza, "fuente": " ".join(m.group(0).split())}

    @staticmethod
    def _proveedor(texto: str) -> dict:
        m = EMISOR.search(texto)
        if m:
            return {"valor": m.group(1).strip(), "confianza": 1.0, "fuente": m.group(0).strip()}
        for linea in texto.splitlines():
            l = linea.strip()
            if EMPRESA.search(l) and "miralmar" not in l.lower() and len(l) < 60 and ":" not in l:
                return {"valor": re.sub(r"\s{2,}.*$", "", l), "confianza": 0.9, "fuente": l}
        return {"valor": None, "confianza": 0.7}

    @staticmethod
    def _fecha(campo: dict) -> dict:
        if campo["valor"] is None:
            return campo
        fecha = parse_fecha(campo["valor"])
        if fecha is None:  # "31/02/2026": seguro que está, pero no es válida
            return {**campo, "confianza": 1.0}
        return {**campo, "valor": fecha.isoformat()}

    # --- líneas y notas -------------------------------------------------------------------------

    @staticmethod
    def _lineas(texto: str) -> tuple[list[tuple[str, Decimal]], list]:
        lineas: list[tuple[str, Decimal]] = []
        notas = []
        for linea in texto.splitlines():
            if ETIQUETAS_TOTALES.match(linea) or LINEA_CON_DATO[0].search(linea) or LINEA_CON_DATO[2].search(linea):
                continue
            for patron in LINEA_ITEM:
                m = patron.match(linea)
                if m:
                    concepto = " ".join(m.group("c").strip(" -·").split())
                    importe = parse_importe(m.group("n"))
                    if importe is None or not concepto or ETIQUETAS_TOTALES.match(concepto):
                        break
                    lineas.append((concepto, importe))
                    n = notas_dom.nota(concepto)  # una instrucción disfrazada de línea de detalle
                    if n.es("dirigida_al_sistema") or n.es("pide_saltar_regla"):
                        notas.append(n)
                    break
        return lineas, notas

    @staticmethod
    def _explicada(l: str) -> bool:
        return (
            not l
            or any(p.search(l) for p in LINEA_CON_DATO)
            or any(p.search(l) for p in RELLENO)
            or any(p.match(l) for p in LINEA_ITEM)
            or bool(EMPRESA.search(l) and ":" not in l and len(l) < 60)
        )

    @classmethod
    def _notas(cls, texto: str) -> list:
        """Lo que queda cuando quitas datos, líneas de detalle y plantilla, en párrafos."""
        parrafos: list[list[str]] = []
        actual: list[str] = []
        for linea in texto.splitlines():
            l = linea.strip()
            if cls._explicada(l):
                if actual:
                    parrafos.append(actual)
                    actual = []
                continue
            actual.append(l)
        if actual:
            parrafos.append(actual)
        notas = []
        for parrafo in parrafos:
            t = " ".join(" ".join(parrafo).split())
            for frase in FRASES_RELLENO:
                t = frase.sub("", t)
            t = t.strip(" .")
            if len(t.split()) >= 3:
                notas.append(notas_dom.nota(t))
        return notas

    # --- coherencia ---------------------------------------------------------------------------

    @staticmethod
    def _deducir_importes(campos: dict, lineas: list[tuple[str, Decimal]]) -> None:
        base, iva, total = (parse_importe(str(campos[k]["valor"])) if campos[k]["valor"] is not None else None for k in ("base", "iva", "total"))
        pct = Decimal(str(campos["iva_pct"]["valor"]).replace(",", ".")) if campos["iva_pct"]["valor"] is not None else None
        if base is None and lineas:
            base = sum(n for _, n in lineas)
            campos["base"] = {"valor": float(base), "confianza": 0.6, "fuente": "suma de las líneas"}
        if iva is None and base is not None and total is not None:
            iva = total - base
            campos["iva"] = {"valor": float(iva), "confianza": 0.6, "fuente": "total menos base"}
        if pct is None and iva is not None and base:
            pct = (iva / base * 100).quantize(Decimal("0.01"))
            campos["iva_pct"] = {"valor": float(pct), "confianza": 0.6, "fuente": "deducido de base e IVA"}
        for k in ("base", "iva", "total"):
            if campos[k]["valor"] is not None and not isinstance(campos[k]["valor"], float):
                campos[k]["valor"] = float(parse_importe(str(campos[k]["valor"])))
        if campos["iva_pct"]["valor"] is not None and not isinstance(campos["iva_pct"]["valor"], float):
            campos["iva_pct"]["valor"] = float(str(campos["iva_pct"]["valor"]).replace(",", "."))

    @staticmethod
    def _checks(campos: dict, lineas: list[tuple[str, Decimal]]) -> dict:
        def d(k):
            v = campos[k]["valor"]
            return Decimal(str(v)) if v is not None else None

        base, iva, total, pct = d("base"), d("iva"), d("total"), d("iva_pct")
        return {
            "total_cuadra": (abs(base + iva - total) <= LIMITE) if None not in (base, iva, total) else None,
            "iva_cuadra": (abs((base * pct / 100).quantize(LIMITE) - iva) <= LIMITE) if None not in (base, iva, pct) else None,
            "lineas_cuadran": (abs(sum(n for _, n in lineas) - base) <= LIMITE) if lineas and base is not None else None,
        }

    @staticmethod
    def _pagina(doc: DocumentoInspeccionado, fuente: str) -> int | None:
        for i, texto in enumerate(doc.texto_por_pagina, 1):
            if fuente and fuente.split(" ")[0] in texto:
                return i
        return None
