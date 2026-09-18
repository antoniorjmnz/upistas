"""Lector de PDFs con capa de texto (471 de 500 en La Caja). Sin LLM: rápido y gratis."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.puertos import LecturaFallida


def texto_pdf(ruta: Path) -> str:
    with pymupdf.open(ruta) as doc:
        return "".join(pagina.get_text() for pagina in doc)


class LectorPdfTexto:
    nombre = "pdf_texto"

    def acepta(self, ruta: Path) -> bool:
        return ruta.suffix.lower() == ".pdf"

    def leer(self, ruta: Path) -> FacturaExtraida:
        texto = texto_pdf(ruta)
        if len(texto.strip()) < 30:
            raise LecturaFallida("PDF sin capa de texto (escaneado)")
        # Pendiente: parser de las plantillas de La Caja (issue del extractor determinista).
        raise LecturaFallida("Parser de plantillas aún no implementado")
