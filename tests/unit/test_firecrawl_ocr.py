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


def _respuesta(datos=None, estado=200, headers=None):
    return SimpleNamespace(
        status_code=estado,
        headers=headers or {},
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
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), espera_base=0)(_png())
    assert "detalle sensible" not in str(fallo.value)


def test_respuesta_sin_exito_o_sin_texto_es_fallo():
    post = Mock(return_value=_respuesta({"success": False}))
    with pytest.raises(LecturaFallida):
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), espera_base=0)(_png())

    post = Mock(return_value=_ok("   "))
    with pytest.raises(LecturaFallida, match="sin texto"):
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), espera_base=0)(_png())


def test_los_fallos_de_transporte_se_reintentan():
    """RemoteProtocolError (el plan corta conexiones a la vez) es transitorio: se reintenta."""
    import httpx

    post = Mock(side_effect=[
        httpx.RemoteProtocolError("connection closed"),
        httpx.RemoteProtocolError("connection closed"),
        _ok(),
    ])
    ocr = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), espera_base=0)
    assert ocr(_png()) == TEXTO
    assert post.call_count == 3


def test_un_429_espera_lo_que_pida_el_retry_after():
    post = Mock(side_effect=[_respuesta(estado=429, headers={"retry-after": "5"}), _ok()])
    dormido = []
    ocr = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), espera_base=0, dormir=dormido.append)
    assert ocr(_png()) == TEXTO
    assert dormido == [5.0]


def test_un_error_4xx_no_se_reintenta():
    post = Mock(return_value=_respuesta(estado=403))
    with pytest.raises(LecturaFallida, match="HTTP 403"):
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), espera_base=0)(_png())
    assert post.call_count == 1


def test_agotados_los_intentos_es_fallo_de_lectura():
    import httpx

    post = Mock(side_effect=httpx.RemoteProtocolError("connection closed"))
    with pytest.raises(LecturaFallida, match="RemoteProtocolError"):
        FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), intentos=3, espera_base=0)(_png())
    assert post.call_count == 3


def test_el_cerrojo_serializa_las_llamadas_entre_procesos(tmp_path):
    """Con cerrojo, la llamada pasa por el fichero de bloqueo compartido y sigue funcionando."""
    cerrojo = tmp_path / ".firecrawl.lock"
    post = Mock(return_value=_ok())
    ocr = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post), cerrojo=cerrojo)
    assert ocr(_png()) == TEXTO
    assert cerrojo.exists()


def test_el_markdown_con_tablas_vuelve_como_texto_plano():
    markdown = (
        "## Catering Hermanos Pico S.L.\n"
        "| Servicio mensual | 683,33 |\n"
        "| --- | --- |\n"
        "| **TOTAL** | 2.480,50 EUR |\n"
        "Pedido: PO-2026-0726"
    )
    post = Mock(return_value=_ok(markdown))
    texto = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=post))(_png())
    assert "|" not in texto and "#" not in texto and "**" not in texto
    assert "Servicio mensual 683,33" in texto
    assert "TOTAL 2.480,50 EUR" in texto
    assert "PO-2026-0726" in texto  # los guiones sueltos de los datos no se tocan


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


def test_un_proveedor_desconocido_falla_en_claro_en_vez_de_usar_fal():
    """OCR_PROVIDER con una errata no debe caer en Fal silenciosamente."""
    from dataclasses import replace

    from upistas.infra import contenedor

    original = contenedor.settings
    try:
        contenedor.configurar(replace(original, usar_ocr=True, ocr_provider="otro"))
        with pytest.raises(ValueError, match="OCR_PROVIDER"):
            contenedor._ocr()
    finally:
        contenedor.configurar(original)
