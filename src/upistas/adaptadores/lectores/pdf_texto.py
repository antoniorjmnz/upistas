"""Lector de PDFs con capa de texto (471 de 500 en La Caja). Sin IA: rápido y gratis.

Pendiente (#23, equipo de lectura): el parser de las ~10 plantillas de La Caja. Mientras tanto
acepta los PDFs con texto y devuelve "no implementado", así el pipeline sigue y esas facturas
acaban en ESCALAR con ese motivo.
"""
from __future__ import annotations

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.puertos import DocumentoInspeccionado, LecturaFallida


class LectorPdfTexto:
    nombre = "pdf_texto"
    metodo = "texto_determinista"

    def acepta(self, doc: DocumentoInspeccionado) -> bool:
        return doc.tipo == "texto"

    def leer(self, doc: DocumentoInspeccionado) -> FacturaExtraida:
        raise LecturaFallida("parser de plantillas pendiente (#23)")
