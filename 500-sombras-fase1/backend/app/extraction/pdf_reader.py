from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

from .image_preprocess import preprocess_for_ocr


@dataclass
class RoutedPage:
    page_number: int
    route: str
    text: str | None = None
    image_path: str | None = None


INVOICE_KEYWORDS = {
    "factura",
    "invoice",
    "total",
    "iva",
    "nif",
    "cif",
    "pedido",
    "iban",
    "fecha",
}


def text_is_useful(text: str) -> bool:
    if not text:
        return False

    clean = text.strip()

    if len(clean) < 80:
        return False

    words = re.findall(
        r"\b[\wÁÉÍÓÚÜÑáéíóúüñ]+\b",
        clean,
    )

    if len(words) < 10:
        return False

    normalized = clean.lower()

    keyword_hits = sum(
        keyword in normalized
        for keyword in INVOICE_KEYWORDS
    )

    if len(words) >= 40:
        return True

    return keyword_hits >= 2


def render_page_to_png(
    page: fitz.Page,
    output_path: Path,
    dpi: int = 400,
) -> None:

    zoom = dpi / 72

    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(
            zoom,
            zoom,
        ),
        alpha=False,
    )

    pixmap.save(
        str(output_path)
    )


def route_pdf(
    pdf_path: str,
    tmp_dir: str = "tmp/pages",
) -> list[RoutedPage]:

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el PDF: {path}"
        )

    output_dir = Path(tmp_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    document = fitz.open(path)

    try:

        pages: list[RoutedPage] = []

        for index, page in enumerate(document):

            page_number = index + 1

            native_text = page.get_text(
                "text"
            ).strip()

            #
            # TEXTO NATIVO
            #
            if text_is_useful(native_text):

                pages.append(
                    RoutedPage(
                        page_number=page_number,
                        route="native_text",
                        text=native_text,
                    )
                )

                continue

            #
            # SCAN / IMAGEN
            #

            raw_image_path = (
                output_dir
                / f"{path.stem}_page_{page_number}_raw.png"
            )

            ocr_image_path = (
                output_dir
                / f"{path.stem}_page_{page_number}_ocr.png"
            )

            #
            # 1. Renderizamos a alta resolución
            #
            render_page_to_png(
                page=page,
                output_path=raw_image_path,
                dpi=320,
            )

            #
            # 2. Preprocesamos para OCR
            #
            preprocess_for_ocr(
                str(raw_image_path),
                str(ocr_image_path),
            )

            #
            # 3. Fal recibirá la imagen procesada,
            #    NO la página original
            #
            pages.append(
                RoutedPage(
                    page_number=page_number,
                    route="fal_ocr",
                    image_path=str(
                        ocr_image_path
                    ),
                )
            )

        return pages

    finally:

        document.close()