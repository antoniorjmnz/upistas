"""Marcar PDFs con PyMuPDF: encontrar lo escondido con el mismo inspector de la ingesta y dibujar encima.

Implementa el puerto `MarcadorPdf` de `aplicacion/marcar_pdf.py`. Vive fuera de `lectores/` a propósito:
esa carpeta forma parte de la huella que decide si hay que volver a leer las facturas, y marcar no es leer.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from upistas.adaptadores.lectores.pdf import MAX_BYTES, MAX_PAGINAS, ocultos_de_pagina
from upistas.aplicacion.marcar_pdf import OcultosDelPdf, PdfNoMarcable, TrozoOculto

ROJO = (0.8, 0, 0)
TINTA = (0.15, 0.15, 0.15)
HOJA = (595, 842)  # A4 en puntos
MARGEN = 40
CUERPO, TITULO = 10, 14  # tamaños de letra
INTERLINEA = 1.45


class MarcadorPdfMuPDF:
    def ocultos(self, ruta: Path) -> OcultosDelPdf:
        trozos: list[TrozoOculto] = []
        sin_comprobar: list[int] = []
        with _abierto(ruta) as pdf:
            for pagina in pdf:
                encontrados, aviso = ocultos_de_pagina(pagina)
                if aviso:
                    sin_comprobar.append(pagina.number + 1)
                trozos += [
                    TrozoOculto(pagina.number + 1, tuple(s["caja"]), s["texto"], tuple(s["motivos"])) for s in encontrados
                ]
        return OcultosDelPdf(tuple(trozos), tuple(sin_comprobar))

    def marcar(self, ruta: Path, trozos: Sequence[TrozoOculto], pagina_final: Sequence[str]) -> bytes:
        with _abierto(ruta) as pdf:
            for t in trozos:
                pdf[t.pagina - 1].draw_rect(pymupdf.Rect(t.caja), color=ROJO, width=1.2)
            if pagina_final:
                _escribir_pagina_final(pdf, list(pagina_final))
            return pdf.tobytes()


@contextmanager
def _abierto(ruta: Path) -> Iterator[pymupdf.Document]:
    """Abre el PDF con los mismos topes y cuidados que el inspector; cualquier fallo es PdfNoMarcable."""
    if not ruta.is_file():
        raise PdfNoMarcable("El PDF ya no está donde lo dejamos.")
    if ruta.stat().st_size > MAX_BYTES:
        raise PdfNoMarcable("Este PDF es demasiado grande para marcarlo.")
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        pdf = pymupdf.open(ruta)
    except Exception as exc:  # pymupdf lanza tipos distintos según el fallo
        raise PdfNoMarcable("Este PDF está dañado y no se puede abrir.") from exc
    with pdf:
        if pdf.needs_pass:
            raise PdfNoMarcable("Este PDF está protegido con contraseña: no se puede marcar.")
        if pdf.page_count > MAX_PAGINAS:
            raise PdfNoMarcable(f"Este PDF tiene {pdf.page_count} páginas: demasiadas para marcarlo.")
        try:
            yield pdf
        except Exception as exc:
            raise PdfNoMarcable("Este PDF está dañado: no se ha podido recorrer.") from exc


def _lineas(texto: str, fuente: pymupdf.Font, ancho: float, tamano: int) -> list[str]:
    """Parte un párrafo en líneas que quepan en `ancho` puntos. Una palabra más ancha que la hoja se parte donde haga falta."""

    def cabe(s: str) -> bool:
        return fuente.text_length(s, fontsize=tamano) <= ancho

    lineas: list[str] = []
    actual = ""
    for palabra in texto.split():
        candidata = f"{actual} {palabra}" if actual else palabra
        if cabe(candidata):
            actual = candidata
            continue
        if actual:
            lineas.append(actual)
        actual = ""
        for letra in palabra:
            if actual and not cabe(actual + letra):
                lineas.append(actual)
                actual = ""
            actual += letra
    if actual:
        lineas.append(actual)
    return lineas or [""]


def _escribir_pagina_final(pdf: pymupdf.Document, parrafos: list[str]) -> None:
    """Una página nueva (o las que hagan falta) con los párrafos; el primero es el título."""
    fuente = pymupdf.Font("helv")
    # Lo que la letra no sabe pintar (emojis, otros alfabetos) sale como un punto: si no, MuPDF
    # incrusta una fuente de varios megas para un carácter.
    parrafos = ["".join(c if fuente.has_glyph(ord(c)) else "·" for c in p) for p in parrafos]
    pagina = pdf.new_page(width=HOJA[0], height=HOJA[1])
    escritor = pymupdf.TextWriter(pagina.rect, color=TINTA)
    y = MARGEN + TITULO
    for i, parrafo in enumerate(parrafos):
        tamano = TITULO if i == 0 else CUERPO
        for linea in _lineas(parrafo, fuente, HOJA[0] - 2 * MARGEN, tamano):
            if y > HOJA[1] - MARGEN:
                escritor.write_text(pagina)
                pagina = pdf.new_page(width=HOJA[0], height=HOJA[1])
                escritor = pymupdf.TextWriter(pagina.rect, color=TINTA)
                y = MARGEN + tamano
            escritor.append((MARGEN, y), linea, font=fuente, fontsize=tamano)
            y += tamano * INTERLINEA
        y += CUERPO * 0.6  # aire entre párrafos
    escritor.write_text(pagina)
