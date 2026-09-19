"""Lector de escaneados (29 de 500 en La Caja): OCR página a página y el mismo parser que el texto.

El OCR lo hace un servicio externo (fal.ai, GOT-OCR2, idea de Pablo) que cuesta dinero y tarda
segundos por página; el pipeline cachea cada lectura por sha256, así que un escaneado solo pasa
por aquí una vez. Lo que el OCR no puede garantizar (que los importes cuadren) se marca como
duda, nunca como incumplimiento: un dígito mal leído no es una factura mal hecha.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import replace

import pymupdf

from upistas.adaptadores.lectores.pdf_texto import LectorPdfTexto
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.puertos import DocumentoInspeccionado, LecturaFallida

Ocr = Callable[[bytes], str]  # imagen PNG de una página → texto (o LecturaFallida)

CONFIANZA_SI_NO_CUADRA = 0.6  # por debajo del mínimo: las reglas lo tratan como dato no leído


class LectorPdfOcr:
    nombre = "pdf_ocr"
    metodo = "ocr_determinista"

    def __init__(self, ocr: Ocr, dpi: int = 200, parser: LectorPdfTexto | None = None):
        self._ocr = ocr
        self._dpi = dpi
        self._parser = parser or LectorPdfTexto()

    def acepta(self, doc: DocumentoInspeccionado) -> bool:
        return doc.tipo == "escaneado"

    def leer(self, doc: DocumentoInspeccionado) -> FacturaExtraida:
        t0 = time.perf_counter()
        textos: list[str] = []
        errores: list[str] = []
        for numero, png in enumerate(self._paginas(doc), 1):
            try:
                textos.append(self._ocr(png))
            except LecturaFallida as exc:
                textos.append("")
                errores.append(f"Página {numero}: {exc}")
        if not any(t.strip() for t in textos):
            raise LecturaFallida("; ".join(errores) or "OCR sin texto")

        extraida = self._parser.leer(replace(doc, texto_por_pagina=tuple(textos)))
        datos = extraida.model_dump(mode="json")  # con los null: "valor" es obligatorio aunque falte
        datos.update(metodo=self.metodo, lector=self.nombre)
        if errores:
            datos["errores"] = errores
        if datos.get("checks", {}).get("total_cuadra") is False:
            for campo in ("base", "iva", "total"):
                c = datos["campos"].get(campo)
                if c and c.get("valor") is not None:
                    c["confianza"] = min(c["confianza"], CONFIANZA_SI_NO_CUADRA)
        datos.setdefault("coste", {})["segundos"] = round(time.perf_counter() - t0, 4)
        return FacturaExtraida.model_validate(datos)

    def _paginas(self, doc: DocumentoInspeccionado) -> Iterator[bytes]:
        try:
            with pymupdf.open(doc.ruta) as pdf:
                for pagina in pdf:
                    yield pagina.get_pixmap(dpi=self._dpi).tobytes("png")
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise LecturaFallida(f"no se puede renderizar el PDF: {exc}") from exc
