"""Marcar PDFs con PyMuPDF: encontrar lo escondido con el mismo inspector de la ingesta, localizar los datos
que hacen saltar las alarmas y dibujar encima.

Implementa el puerto `MarcadorPdf` de `aplicacion/marcar_pdf.py`. Vive fuera de `lectores/` a propósito:
esa carpeta forma parte de la huella que decide si hay que volver a leer las facturas, y marcar no es leer.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from upistas.adaptadores.lectores.pdf import MAX_BYTES, MAX_PAGINAS, ocultos_de_pagina

MAX_TROZOS = 300  # más marcas que esto (rojas o naranjas) no ayudan a quien revisa: se señalan y transcriben las primeras
MAX_HALLAZGOS = 50  # por texto buscado: un dato repetido por toda la factura no se rastrea hasta el infinito
from upistas.aplicacion.marcar_pdf import ENCABEZADOS, Hallazgo, Marca, OcultosDelPdf, PdfNoMarcable, TrozoOculto

ROJO = (0.8, 0, 0)
NARANJA = (0.93, 0.45, 0)
NARANJA_CLARO = (1, 0.93, 0.82)
TINTA = (0.15, 0.15, 0.15)
HOJA = (595, 842)  # A4 en puntos
MARGEN = 40
CUERPO, TITULO, ENCABEZADO, ETIQUETA = 10, 14, 12, 8  # tamaños de letra
INTERLINEA = 1.45
HUECO = 6  # puntos: dos recuadros de la misma línea más separados que esto son dos hallazgos distintos
AIRE = (-2, -1, 2, 1)  # cuánto sobresale el recuadro naranja del dato: a los lados, un poco; arriba y abajo, casi nada


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

    def localizar(self, ruta: Path, textos: Sequence[str]) -> dict[str, tuple[Hallazgo, ...]]:
        """Dónde aparece cada texto. `search_for` encuentra también lo que va partido en dos líneas
        (devuelve un recuadro por línea) y no distingue mayúsculas de minúsculas."""
        hallado: dict[str, list[Hallazgo]] = {}
        with _abierto(ruta) as pdf:
            for pagina in pdf:
                for texto in textos:
                    sitios = hallado.setdefault(texto, [])
                    if len(sitios) >= MAX_HALLAZGOS:
                        continue
                    for caja in _agrupadas(pagina.search_for(texto)):
                        sitios.append(Hallazgo(pagina.number + 1, tuple(round(v, 2) for v in caja)))
        return {t: tuple(s) for t, s in hallado.items() if s}

    def marcar(self, ruta: Path, trozos: Sequence[TrozoOculto], marcas: Sequence[Marca], pagina_final: Sequence[str]) -> bytes:
        with _abierto(ruta) as pdf:
            for t in list(trozos)[:MAX_TROZOS]:
                pdf[t.pagina - 1].draw_rect(pymupdf.Rect(t.caja), color=ROJO, width=1.2)
            for m in list(marcas)[:MAX_TROZOS]:
                _rodear(pdf[m.pagina - 1], m)
            if pagina_final:
                _escribir_pagina_final(pdf, list(pagina_final))
            return pdf.tobytes()


def _agrupadas(cajas: Sequence[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """Un texto partido en varias líneas seguidas es un solo hallazgo: sus recuadros se funden en uno.
    Dos recuadros van seguidos si el segundo empieza donde acaba el primero, a menos de media línea
    de distancia (las líneas de una factura se tocan o casi), o si están en la misma línea y pegados
    (a menos de HUECO puntos: «Base 1.000,00      Total 1.000,00» son dos hallazgos, no uno)."""
    grupos: list[pymupdf.Rect] = []
    for caja in cajas:
        anterior = grupos[-1] if grupos else None
        if anterior is None:
            grupos.append(pymupdf.Rect(caja))
            continue
        linea_siguiente = -3 <= caja.y0 - anterior.y1 <= 0.6 * caja.height
        misma_linea = abs(caja.y0 - anterior.y0) < 2 and -3 <= caja.x0 - anterior.x1 < HUECO
        if linea_siguiente or misma_linea:
            grupos[-1] = anterior | caja
        else:
            grupos.append(pymupdf.Rect(caja))
    return grupos


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


def _pintable(texto: str, fuente: pymupdf.Font) -> str:
    """Lo que la letra no sabe pintar (emojis, otros alfabetos) sale como un punto: si no, MuPDF
    incrusta una fuente de varios megas para un carácter."""
    return "".join(c if fuente.has_glyph(ord(c)) else "·" for c in texto)


def _con_aire(pagina: pymupdf.Page, caja: pymupdf.Rect) -> pymupdf.Rect:
    """El recuadro sobresale AIRE del dato, salvo por arriba o por abajo cuando el renglón vecino está
    pegado (el TOTAL en negrita justo debajo del IVA): por ese lado se queda a la altura de la línea."""
    con_aire = caja + AIRE
    vecinas = [r for r in (pymupdf.Rect(p[:4]) for p in pagina.get_text("words")) if not r.intersects(caja)]
    arriba = pymupdf.Rect(caja.x0, con_aire.y0, caja.x1, caja.y0)
    abajo = pymupdf.Rect(caja.x0, caja.y1, caja.x1, con_aire.y1)
    y0 = caja.y0 if any(r.intersects(arriba) for r in vecinas) else con_aire.y0
    y1 = caja.y1 if any(r.intersects(abajo) for r in vecinas) else con_aire.y1
    return pymupdf.Rect(con_aire.x0, y0, con_aire.x1, y1)


def _rodear(pagina: pymupdf.Page, marca: Marca) -> None:
    """Un recuadro naranja alrededor del dato y su etiqueta al lado (una línea por regla que lo señala):
    a la derecha, encima o debajo, en el primer hueco sin texto; si no hay ninguno, encima, sobre un
    fondo claro para que se lea igual."""
    fuente = pymupdf.Font("helv")
    caja = _con_aire(pagina, pymupdf.Rect(marca.caja))
    pagina.draw_rect(caja, color=NARANJA, width=1.2)
    lineas = [_pintable(linea, fuente) for linea in marca.etiqueta.split("\n")]
    ancho = max(fuente.text_length(linea, fontsize=ETIQUETA) for linea in lineas) + 4
    paso = ETIQUETA + 3
    alto = paso * len(lineas)
    hoja = pagina.rect
    x0 = max(0.0, min(caja.x0, hoja.width - ancho))
    huecos = [
        pymupdf.Rect(caja.x1 + 3, caja.y0, caja.x1 + 3 + ancho, caja.y0 + alto),  # a la derecha
        pymupdf.Rect(x0, caja.y0 - alto, x0 + ancho, caja.y0 - 0.5),  # encima
        pymupdf.Rect(x0, caja.y1 + 0.5, x0 + ancho, caja.y1 + alto),  # debajo
    ]
    libres = [h for h in huecos if hoja.contains(h) and not pagina.get_text("text", clip=h).strip()]
    fondo = libres[0] if libres else huecos[1] if huecos[1].y0 >= 0 else huecos[2]
    pagina.draw_rect(fondo, color=None, fill=NARANJA_CLARO, width=0)
    for i, linea in enumerate(lineas):
        y = fondo.y0 + paso * (i + 1) - 2.5
        pagina.insert_text((fondo.x0 + 2, y), linea, fontsize=ETIQUETA, fontname="helv", color=NARANJA, rotate=pagina.rotation)


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
    """Una página nueva (o las que hagan falta) con los párrafos; el primero es el título y los que están
    en ENCABEZADOS son títulos de apartado, en negrita."""
    normal, negrita = pymupdf.Font("helv"), pymupdf.Font("hebo")
    if len(parrafos) > MAX_TROZOS + 1:
        parrafos = [*parrafos[: MAX_TROZOS + 1], f"… y {len(parrafos) - MAX_TROZOS - 1} trozos más que no se transcriben."]
    pagina = pdf.new_page(width=HOJA[0], height=HOJA[1])
    escritor = pymupdf.TextWriter(pagina.rect, color=TINTA)
    y = MARGEN + TITULO
    for i, parrafo in enumerate(parrafos):
        encabezado = i == 0 or parrafo in ENCABEZADOS
        fuente = negrita if encabezado else normal
        tamano = TITULO if i == 0 else ENCABEZADO if encabezado else CUERPO
        if encabezado and i > 0:
            y += CUERPO  # aire antes de un apartado
        for linea in _lineas(_pintable(parrafo, fuente), fuente, HOJA[0] - 2 * MARGEN, tamano):
            if y > HOJA[1] - MARGEN:
                escritor.write_text(pagina)
                pagina = pdf.new_page(width=HOJA[0], height=HOJA[1])
                escritor = pymupdf.TextWriter(pagina.rect, color=TINTA)
                y = MARGEN + tamano
            escritor.append((MARGEN, y), linea, font=fuente, fontsize=tamano)
            y += tamano * INTERLINEA
        y += CUERPO * 0.6  # aire entre párrafos
    escritor.write_text(pagina)
