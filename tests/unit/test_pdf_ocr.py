"""El lector de escaneados: renderiza, pasa cada página por el OCR (aquí uno falso) y usa el parser."""
import pymupdf
import pytest

from upistas.adaptadores.lectores.pdf_ocr import LectorPdfOcr
from upistas.puertos import DocumentoInspeccionado, LecturaFallida

TEXTO = """FACTURA
Factura Nº: F-2026-001
Fecha: 08/01/2026
Emisor: Demo S.L. · NIF: B12345678
IBAN: ES12 1234 1234 1234 1234 1234
Pedido: PO-2026-0001
Base imponible: 100,00
IVA (21%): 21,00
Total: 121,00
"""


def escaneado(tmp_path, paginas=1):
    ruta = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        for _ in range(paginas):
            pdf.new_page()
        pdf.save(ruta)
    return DocumentoInspeccionado("scan.pdf", str(ruta), "0" * 64, ruta.stat().st_size, "escaneado", paginas)


def test_solo_acepta_escaneados(tmp_path):
    lector = LectorPdfOcr(lambda png: TEXTO)
    assert lector.acepta(escaneado(tmp_path))
    assert not lector.acepta(DocumentoInspeccionado("a.pdf", "a.pdf", "", 0, "texto"))


def test_lee_una_factura_escaneada(tmp_path):
    recibidas = []

    def ocr(png):
        recibidas.append(png)
        return TEXTO

    f = LectorPdfOcr(ocr).leer(escaneado(tmp_path))
    assert len(recibidas) == 1 and recibidas[0][:8] == b"\x89PNG\r\n\x1a\n"
    assert f.metodo.value == "ocr_determinista" and f.lector == "pdf_ocr"
    assert f.campos.nif.valor == "B12345678" and f.campos.pedido.valor == "PO-2026-0001" and f.campos.total.valor == 121
    assert f.errores is None and f.coste.segundos >= 0


def test_una_pagina_sin_ocr_deja_error_pero_no_pierde_el_resto(tmp_path):
    def ocr(png):
        if ocr.llamadas:
            raise LecturaFallida("OCR sin texto")
        ocr.llamadas.append(1)
        return TEXTO

    ocr.llamadas = []
    f = LectorPdfOcr(ocr).leer(escaneado(tmp_path, paginas=2))
    assert f.errores == ["Página 2: OCR sin texto"] and f.campos.total.valor == 121


def test_si_no_sale_texto_de_ninguna_pagina_falla(tmp_path):
    def ocr(png):
        raise LecturaFallida("OCR sin texto")

    with pytest.raises(LecturaFallida, match="Página 1"):
        LectorPdfOcr(ocr).leer(escaneado(tmp_path))


def test_importes_que_no_cuadran_son_duda_no_incumplimiento(tmp_path):
    f = LectorPdfOcr(lambda png: TEXTO.replace("Total: 121,00", "Total: 127,00")).leer(escaneado(tmp_path))
    assert f.checks.total_cuadra is False
    assert f.campos.total.confianza < 0.8 and f.campos.base.confianza < 0.8 and f.campos.nif.confianza >= 0.8
