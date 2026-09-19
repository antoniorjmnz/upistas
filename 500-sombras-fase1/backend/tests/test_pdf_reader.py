from pathlib import Path

import pymupdf as fitz

from app.extraction.pdf_reader import (
    route_pdf,
    text_is_useful,
)


def test_empty_text_is_not_useful():
    assert text_is_useful("") is False


def test_short_text_is_not_useful():
    assert text_is_useful("Factura 1") is False


def test_invoice_text_is_useful():
    text = """
    FACTURA FA-1001
    Proveedor Demo SL
    NIF B12345678
    Fecha 01/09/2026
    Pedido PO-2026-0001
    Base imponible 100,00 EUR
    IVA 21% 21,00 EUR
    TOTAL 121,00 EUR
    Información adicional de la factura.
    """

    assert text_is_useful(text) is True


def test_image_only_page_goes_to_fal(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"

    document = fitz.open()
    document.new_page()
    document.save(pdf)
    document.close()

    pages = route_pdf(
        str(pdf),
        tmp_dir=str(tmp_path / "pages"),
    )

    assert len(pages) == 1
    assert pages[0].route == "fal_ocr"
    assert Path(
        pages[0].image_path
    ).exists()


def test_text_page_goes_to_native_text(tmp_path: Path):
    pdf = tmp_path / "digital.pdf"

    document = fitz.open()
    page = document.new_page()

    page.insert_text(
        (72, 72),
        (
            "FACTURA FA-1001\n"
            "Proveedor Demo SL\n"
            "NIF B12345678\n"
            "Fecha 01/09/2026\n"
            "Pedido PO-2026-0001\n"
            "Base imponible 100,00 EUR\n"
            "IVA 21% 21,00 EUR\n"
            "TOTAL 121,00 EUR\n"
            "Información adicional para asegurar "
            "una cantidad suficiente de texto."
        ),
    )

    document.save(pdf)
    document.close()

    pages = route_pdf(
        str(pdf),
        tmp_dir=str(tmp_path / "pages"),
    )

    assert len(pages) == 1
    assert pages[0].route == "native_text"
