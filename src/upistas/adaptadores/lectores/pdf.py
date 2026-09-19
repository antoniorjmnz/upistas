"""Abrir un PDF con cuidado: qué es (texto, escaneado, blanco, roto, cifrado) y qué trae de raro.

Los mentores probarán PDFs maliciosos y rotos. Aquí nunca se ejecuta nada del documento: solo se
mira su estructura y se apuntan alertas. 492 de los 500 de La Caja tienen la tabla xref rota y
MuPDF la repara al abrirlos; eso se anota, no se penaliza.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import pymupdf

from upistas.puertos import DocumentoInspeccionado

MAX_PAGINAS = 50
MAX_BYTES = 25 * 1024 * 1024
MIN_TEXTO = 30  # menos caracteres que esto = no hay capa de texto
INVISIBLES = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
ACTIVO = re.compile(rb"/(JavaScript|JS|Launch|OpenAction|AA|EmbeddedFile|RichMedia)\b")


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


class InspectorPdf:
    def inspeccionar(self, ruta: Path) -> DocumentoInspeccionado:
        ruta = Path(ruta)
        alertas: list[str] = []
        if not ruta.is_file():
            return DocumentoInspeccionado(ruta.name, str(ruta), "", 0, "otro", alertas=("el fichero no existe",))
        tamano = ruta.stat().st_size
        sha = sha256_de(ruta) if tamano <= MAX_BYTES else ""

        def doc(tipo: str, paginas: int = 0, texto: tuple[str, ...] = (), extra: list[str] | None = None) -> DocumentoInspeccionado:
            return DocumentoInspeccionado(ruta.name, str(ruta), sha, tamano, tipo, paginas, texto, tuple(alertas + (extra or [])))

        if tamano == 0:
            return doc("blanco", extra=["fichero vacío"])
        if tamano > MAX_BYTES:
            return doc("otro", extra=[f"demasiado grande: {tamano // 1024 // 1024} MB"])
        if ruta.suffix.lower() != ".pdf":
            alertas.append(f"extensión {ruta.suffix or 'sin extensión'}")

        pymupdf.TOOLS.mupdf_display_errors(False)
        try:
            pdf = pymupdf.open(ruta)
        except Exception as exc:  # pymupdf lanza tipos distintos según el fallo
            return doc("roto", extra=[f"no se puede abrir: {type(exc).__name__}"])

        with pdf:
            if pdf.needs_pass:
                return doc("cifrado", extra=["protegido con contraseña"])
            if pdf.is_repaired:
                alertas.append("estructura reparada al abrir")
            if not pdf.is_pdf:
                alertas.append(f"no es un PDF: {pdf.metadata.get('format', '?')}")
            n_paginas = pdf.page_count
            if n_paginas == 0:
                return doc("blanco", extra=["sin páginas"])
            if n_paginas > MAX_PAGINAS:
                return doc("otro", n_paginas, extra=[f"{n_paginas} páginas: demasiadas para una factura"])

            alertas += _contenido_activo(pdf)
            paginas: list[str] = []
            imagenes = 0
            for pagina in pdf:
                try:
                    paginas.append(pagina.get_text())
                    imagenes += len(pagina.get_images(full=False))
                    alertas.extend(_visibilidad_texto(pagina))
                except Exception as exc:
                    alertas.append(f"página {pagina.number + 1} ilegible: {type(exc).__name__}")
                    paginas.append("")

        texto = "".join(paginas)
        if INVISIBLES.search(texto):
            alertas.append("caracteres invisibles en el texto")
        alertas.extend(_controles_fuera_de_campos(texto))
        raros = sum(1 for c in texto if unicodedata.category(c) in ("Cf", "Co", "Cs"))
        if raros > 20:
            alertas.append(f"{raros} caracteres de control o privados")

        if len(texto.strip()) >= MIN_TEXTO:
            return doc("texto", n_paginas, tuple(paginas))
        if imagenes:
            return doc("escaneado", n_paginas, tuple(paginas))
        return doc("blanco", n_paginas, tuple(paginas), extra=["sin texto ni imágenes"])


def _controles_fuera_de_campos(texto: str) -> list[str]:
    for linea in texto.splitlines():
        controles = {c for c in linea if unicodedata.category(c) in ("Cf", "Cc") and c != "\t"}
        if not controles:
            continue
        limpia = "".join(c for c in linea if c not in controles).strip()
        iban = re.fullmatch(r"(?:IBAN|CUENTA (?:DE ABONO|BANCARIA)(?:\s*\(IBAN\))?)\s*[:.]?\s*ES[\d\s.-]+", limpia, re.I)
        importe = re.fullmatch(
            r"(?:TOTAL(?: FACTURA| A PAGAR)?|BASE(?: IMPONIBLE)?|IVA(?:\s*\(?\s*\d+(?:[.,]\d+)?\s*%\s*\)?)?)"
            r"[\s.:]*(?:EUR|€)?\s*[+-]?\d[\d\s.,]*\s*(?:EUR|€)?", limpia, re.I,
        )
        if controles <= {"\u200b", "\ufeff", "\u00ad"} and (iban or importe):
            continue
        codigos = ", ".join(sorted(f"U+{ord(c):04X}" for c in controles))
        return [f"texto potencialmente oculto: controles Unicode fuera de campos numéricos ({codigos}); muestra={ascii(linea[:120])}"]
    return []


def _visibilidad_texto(pagina) -> list[str]:
    try:
        spans = pagina.get_texttrace()
        dibujos = pagina.get_drawings()
        if len(spans) > 10000 or len(dibujos) > 2000:
            return [f"visibilidad del texto no verificable: página {pagina.number + 1}, estructura demasiado compleja"]
        opacos = [d for d in dibujos if d.get("fill") is not None and d.get("fill_opacity", 1) >= 0.99
                  and len(d.get("items", [])) == 1 and d["items"][0][0] == "re"]
        imagenes = [(i, pymupdf.Rect(b)) for i, (tipo, b) in enumerate(pagina.get_bboxlog()) if tipo == "fill-image"]
        visible = pymupdf.Rect(0, 0, pagina.cropbox.width, pagina.cropbox.height)
        encontrados = {}
        for span in spans:
            texto = "".join(chr(c[0]) for c in span.get("chars", ()) if 0 <= c[0] <= 0x10FFFF).strip()
            if not texto:
                continue
            caja = pymupdf.Rect(span["bbox"])
            orden = span.get("seqno", -1)
            motivos = []
            if span.get("type") == 3:
                motivos.append("modo de texto invisible")
            if span.get("opacity", 1) <= 0.05:
                motivos.append("texto transparente")
            if span.get("size", 10) <= 2:
                motivos.append("texto de tamaño ínfimo")
            if not visible.intersects(caja):
                motivos.append("texto fuera del área visible")
            fondos = [d for d in opacos if d.get("seqno", -1) < orden and d["rect"].contains(caja)]
            fondo = max(fondos, key=lambda d: d.get("seqno", -1), default=None)
            color = span.get("color", ())
            rgb = fondo["fill"] if fondo else (1, 1, 1)
            luminosidad = sum(c * p for c, p in zip(rgb, (0.2126, 0.7152, 0.0722))) if len(rgb) == 3 else rgb[0]
            if color and min(color) >= 0.95 and luminosidad >= 0.85:
                motivos.append("texto casi blanco sin fondo oscuro comprobable")
            if any(d.get("seqno", -1) > orden and d["rect"].contains(caja) for d in opacos) or any(
                i > orden and r.contains(caja) for i, r in imagenes
            ):
                motivos.append("texto potencialmente tapado por contenido posterior")
            for motivo in motivos:
                encontrados.setdefault(motivo, ascii(texto[:120]))
        return [f"texto potencialmente oculto: página {pagina.number + 1}; {motivo}; muestra={muestra}"
                for motivo, muestra in encontrados.items()]
    except Exception as exc:
        return [f"visibilidad del texto no verificable: página {pagina.number + 1} ({type(exc).__name__})"]


def _contenido_activo(pdf: pymupdf.Document) -> list[str]:
    """JavaScript, acciones automáticas o ficheros incrustados: no tienen sentido en una factura."""
    encontrado: set[str] = set()
    try:
        if pdf.embfile_count() > 0:
            encontrado.add("ficheros incrustados")
        for xref in range(1, min(pdf.xref_length(), 5000)):
            try:
                objeto = pdf.xref_object(xref, compressed=True).encode("latin-1", "ignore")
            except Exception:
                continue
            for m in ACTIVO.finditer(objeto):
                clave = m.group(1).decode()
                if clave in ("JavaScript", "JS"):
                    encontrado.add("JavaScript")
                elif clave in ("Launch", "OpenAction", "AA"):
                    encontrado.add(f"acción automática /{clave}")
                elif clave == "EmbeddedFile":
                    encontrado.add("ficheros incrustados")
                else:
                    encontrado.add("contenido multimedia")
    except Exception:
        encontrado.add("no se pudo revisar la estructura interna")
    return sorted(encontrado)
