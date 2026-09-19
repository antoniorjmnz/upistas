"""FirecrawlOCR: el PNG se envuelve en PDF y va a /v2/parse; los fallos son LecturaFallida sin detalles."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest

from upistas.adaptadores.lectores.firecrawl_ocr import FirecrawlOCR
from upistas.adaptadores.lectores.pdf_unificado import LectorPdfUnificado
from upistas.puertos import LecturaFallida

TEXTO = "FACTURA\nFactura: FA-1 Fecha: 01/01/2026\nPedido: PO-2026-0001\nIBAN: ES2100491500051234567890\nTOTAL: 121,00"


def _png() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20))
    return pix.tobytes("png")


def _respuesta(datos, estado=200):
    return SimpleNamespace(
        status_code=estado,
        raise_for_status=Mock(),
        json=Mock(return_value=datos),
    )


def _ok(markdown=TEXTO):
    return _respuesta({"success": True, "data": {"pages": [{"pageNumber": 1, "markdown": markdown}]}})


def test_la_pagina_va_a_parse_en_modo_ocr_y_vuelve_el_markdown():
    post = Mock(return_value=_ok())
    ocr = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))

    assert ocr(_png()) == TEXTO

    url, kwargs = post.call_args.args[0], post.call_args.kwargs
    assert url == "https://api.firecrawl.dev/v2/parse"
    opciones = json.loads(kwargs["data"]["options"])
    assert opciones == {"parsers": [{"type": "pdf", "mode": "ocr", "pages": True}]}
    assert kwargs["files"]["file"][2] == "application/pdf"
    assert pymupdf.open(stream=kwargs["files"]["file"][1], filetype="pdf").page_count == 1


def test_sin_paginas_cae_al_markdown_del_documento():
    post = Mock(return_value=_respuesta({"success": True, "data": {"markdown": TEXTO}}))
    assert FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))(_png()) == TEXTO


def test_sin_clave_es_fallo_de_lectura():
    with pytest.raises(LecturaFallida, match="FIRECRAWL_API_KEY"):
        FirecrawlOCR("")(_png())


def test_fallo_de_la_api_es_fallo_de_lectura_sin_exponer_detalles():
    post = Mock(side_effect=RuntimeError("detalle sensible"))
    with pytest.raises(LecturaFallida) as fallo:
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))(_png())
    assert "detalle sensible" not in str(fallo.value)


def test_respuesta_sin_exito_o_sin_texto_es_fallo():
    post = Mock(return_value=_respuesta({"success": False}))
    with pytest.raises(LecturaFallida):
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))(_png())

    post = Mock(return_value=_ok("   "))
    with pytest.raises(LecturaFallida, match="sin texto"):
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))(_png())


def test_el_proveedor_viaja_en_la_clave_de_cache_y_en_la_traza(tmp_path):
    """Con otro proveedor la cache no choca con la de fal y coste.modelo dice quién leyó."""
    ruta = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(ruta)

    post = Mock(return_value=_ok())
    ocr = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))
    lector = LectorPdfUnificado(ocr=ocr, cache_dir=tmp_path / "cache")

    assert "-firecrawl-" in lector._clave("x")

    factura = lector.leer(ruta)
    assert factura.campos.total.valor == 121
    assert factura.coste.modelo == "firecrawl/parse"
    assert any("firecrawl_ocr" in f.name or "-firecrawl-" in f.name for f in (tmp_path / "cache").iterdir())
