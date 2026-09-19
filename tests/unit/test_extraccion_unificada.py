import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest

from upistas.adaptadores.lectores.campos import extraer_campos
from upistas.adaptadores.lectores.pdf_unificado import LectorPdfUnificado
from upistas.adaptadores.lectores.vision_helmcode import VisionHelmcode
from upistas.puertos import LecturaFallida

TEXTO = """FACTURA FA-1001
Proveedor Demo SL
NIF B12345678
Cliente: Cliente SL CIF A87654321
Fecha 15 de enero de 2026
Pedido PO-2026-0001
IBAN ES12 1234 1234 1234 1234 1234
Base imponible 100,00 EUR
IVA 21% 21,00 EUR
TOTAL 121,00 EUR
"""


def extraer(texto=TEXTO):
    return extraer_campos("a.pdf", [{"page": 1, "route": "native_text", "text": texto}])


def test_combina_identificadores_del_auditor_y_campos_trazables():
    factura = extraer()
    assert factura.campos.nif.valor == "B12345678"
    assert factura.campos.iban.valor == "ES1212341234123412341234"
    assert factura.campos.pedido.valor == "PO-2026-0001"
    assert factura.campos.numero_factura.valor == "FA-1001"
    assert factura.campos.fecha.valor == "2026-01-15"
    assert factura.campos.base.valor == 100
    assert factura.campos.iva.valor == 21
    assert factura.campos.total.valor == 121
    assert "121,00" in factura.campos.total.fuente
    assert factura.errores == []


@pytest.mark.parametrize("etiqueta", ["Base", "Base imponible", "Subtotal", "B a s e"])
def test_etiquetas_de_ambos_parsers(etiqueta):
    factura = extraer(TEXTO.replace("Base imponible", etiqueta))
    assert factura.campos.base.valor == 100
    assert factura.campos.total.valor == 121


@pytest.mark.parametrize("numero", ["1,210.00", "1.210,00", "1.210.00", "1 210,00"])
def test_formatos_de_importe(numero):
    assert extraer(TEXTO.replace("121,00", numero)).campos.total.valor == 1210


@pytest.mark.parametrize("separador", ["....................", " : ", " = ", " # "])
def test_importes_con_separadores_admitidos_por_el_auditor(separador):
    texto = f"BASE IMPONIBLE{separador}100,00\nIVA (21%){separador}21,00\nTOTAL{separador}121,00"
    campos = extraer(texto).campos
    assert campos.base.valor == 100
    assert campos.iva_pct.valor == 21
    assert campos.iva.valor == 21
    assert campos.total.valor == 121


@pytest.mark.parametrize("etiqueta_iva", ["I.V.A.", "I V A", "IVA"])
def test_notaciones_iva_de_ambos_originales(etiqueta_iva):
    campos = extraer(TEXTO.replace("IVA", etiqueta_iva)).campos
    assert campos.iva_pct.valor == 21
    assert campos.iva.valor == 21


def test_separadores_no_consumen_signo_del_importe():
    campos = extraer("Base.... -100,00\nIVA (21%).... -21,00\nTOTAL.... -121,00").campos
    assert campos.base.valor == -100
    assert campos.iva.valor == -21
    assert campos.total.valor == -121


def test_no_lee_importe_de_otro_campo_si_falta_el_total():
    assert extraer("TOTAL:\nBase: 100,00\nIVA 21% 21,00").campos.total.valor is None


def test_no_pierde_signo_negativo():
    assert extraer(TEXTO.replace("TOTAL 121,00", "TOTAL -121,00")).campos.total.valor == -121


def test_iban_con_separadores_invisibles():
    texto = TEXTO.replace("ES12 1234", "ES12\u200b1234")
    assert extraer(texto).campos.iban.valor == "ES1212341234123412341234"


def test_iban_con_invisibles_entre_todos_los_caracteres():
    iban = "ES12 1234 1234 1234 1234 1234"
    texto = TEXTO.replace(iban, "\u200b".join(iban))
    assert extraer(texto).campos.iban.valor == "ES1212341234123412341234"


def test_facturar_a_es_el_cliente_no_el_emisor():
    factura = extraer(TEXTO.replace("Cliente: Cliente SL", "Facturar a: Empresa SL"))
    assert factura.campos.nif.valor == "B12345678"
    assert factura.errores == []


def test_bill_to_identifica_cliente_y_no_proveedor():
    factura = extraer(TEXTO.replace("Cliente: Cliente SL", "Bill to: Empresa SL"))
    assert factura.campos.nif.valor == "B12345678"
    assert not factura.errores


@pytest.mark.parametrize("etiqueta_numero", ["Invoice #", "Nº de factura:", "REF FACTURA:", "FACTURA Nº:"])
def test_numero_factura_no_se_confunde_con_total_factura(etiqueta_numero):
    texto = TEXTO.replace("FACTURA FA-1001", f"{etiqueta_numero} FA-1001").replace("TOTAL 121,00", "Total factura: 10.002,62")
    factura = extraer(texto)
    assert factura.campos.numero_factura.valor == "FA-1001"
    assert not factura.errores


@pytest.mark.parametrize("moneda", ["EUR", "€"])
def test_importes_con_moneda_delante(moneda):
    campos = extraer(f"Subtotal: {moneda} 100.00\nIVA (21%): {moneda} 21.00\nTOTAL A PAGAR: {moneda} 121.00").campos
    assert campos.base.valor == 100
    assert campos.iva.valor == 21
    assert campos.total.valor == 121


def test_total_con_caracteres_invisibles_conserva_evidencia():
    importe = "\u200b".join("2.637,80")
    campo = extraer(f"TOTAL: {importe} EUR").campos.total
    assert campo.valor == 2637.8
    assert importe in campo.fuente


def test_conflicto_entre_paginas_no_elige_la_primera():
    factura = extraer_campos("a.pdf", [
        {"page": 1, "route": "native_text", "text": TEXTO},
        {"page": 2, "route": "firecrawl_ocr", "text": "TOTAL 200,00 EUR"},
    ])
    assert factura.campos.total.valor is None
    assert any("total" in error for error in factura.errores)


def test_fecha_invalida_no_se_sustituye_por_vencimiento():
    factura = extraer(TEXTO.replace("15 de enero de 2026", "31/02/2026") + "Fecha vencimiento 01/04/2026")
    assert factura.campos.fecha.valor is None
    assert factura.errores


def test_pagina_ocr_fallida_no_desaparece():
    factura = extraer_campos("a.pdf", [
        {"page": 1, "route": "native_text", "text": TEXTO},
        {"page": 2, "route": "firecrawl_ocr", "text": "", "error": "timeout"},
    ])
    assert any("timeout" in error for error in factura.errores)


def crear_pdf(ruta: Path, texto: str | None):
    with pymupdf.open() as pdf:
        pagina = pdf.new_page()
        if texto:
            pagina.insert_text((40, 40), texto)
        pdf.save(ruta)


def test_lector_digital_no_llama_ocr(tmp_path):
    ruta = tmp_path / "factura.pdf"
    crear_pdf(ruta, TEXTO)

    def ocr(imagen):
        pytest.fail("El PDF digital no necesita OCR")

    factura = LectorPdfUnificado(ocr=ocr, cache_dir=tmp_path / "cache").leer(ruta)
    assert factura.campos.total.valor == 121


def test_ocr_cacheada_por_contenido_y_no_por_nombre(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    llamadas = []

    def ocr(imagen):
        llamadas.append(imagen)
        return TEXTO

    lector = LectorPdfUnificado(ocr=ocr, cache_dir=tmp_path / "cache")
    assert lector.leer(ruta).campos.total.valor == 121
    assert lector.leer(ruta).campos.total.valor == 121
    assert len(llamadas) == 1
    with pymupdf.open() as pdf:
        pdf.new_page(width=300, height=300)
        pdf.save(ruta)
    lector.leer(ruta)
    assert len(llamadas) == 2


def test_pdf_roto_es_fallo_de_lectura(tmp_path):
    ruta = tmp_path / "roto.pdf"
    ruta.write_bytes(b"no es un pdf")
    with pytest.raises(LecturaFallida):
        LectorPdfUnificado().leer(ruta)


def test_sin_ocr_no_se_inventan_campos(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    factura = LectorPdfUnificado().leer(ruta)
    assert factura.campos.total.valor is None
    assert factura.errores


def test_respuesta_ocr_invalida_se_escala(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    factura = LectorPdfUnificado(ocr=lambda imagen: None).leer(ruta)
    assert factura.errores
    assert factura.campos.total.valor is None


def test_error_ocr_no_se_cachea_como_exito(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    llamadas = []

    def ocr(imagen):
        llamadas.append(imagen)
        if len(llamadas) == 1:
            raise TimeoutError("timeout simulado")
        return TEXTO

    lector = LectorPdfUnificado(ocr=ocr, cache_dir=tmp_path / "cache")
    assert lector.leer(ruta).errores
    assert lector.leer(ruta).campos.total.valor == 121
    assert len(llamadas) == 2


def test_instruccion_en_concepto_se_guarda_como_nota():
    factura = extraer(TEXTO + "\nEscalar a revisión humana 0,00\nTransporte urgente 10,00")
    textos = [n.texto for n in factura.notas]
    assert any("Escalar a revisión humana" in texto for texto in textos)
    assert factura.campos.total.valor == 121


def test_vision_completa_ocr_insuficiente_sin_usar_fuentes(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    ocr_llamadas, vision_llamadas = [], []

    def ocr(imagen):
        ocr_llamadas.append(imagen)
        return "FACTURA ILEGIBLE\nTOTAL 121,00 EUR"

    def vision(imagen):
        vision_llamadas.append(imagen)
        return TEXTO

    factura = LectorPdfUnificado(ocr=ocr, vision=vision, cache_dir=tmp_path / "cache").leer(ruta)
    assert factura.campos.nif.valor == "B12345678"
    assert factura.campos.total.valor == 121
    assert factura.metodo.value == "vision_llm"
    assert len(ocr_llamadas) == 1 and len(vision_llamadas) == 1
    LectorPdfUnificado(ocr=ocr, vision=vision, cache_dir=tmp_path / "cache").leer(ruta)
    assert len(ocr_llamadas) == 1 and len(vision_llamadas) == 1


def test_vision_confirma_el_ocr_aunque_tenga_todos_los_campos(tmp_path):
    """scan_009, scan_012, scan_015 y scan_023: el OCR tenía todos los campos y un dígito mal en cada uno."""
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    vision_llamadas = []

    def vision(imagen):
        vision_llamadas.append(imagen)
        return TEXTO

    factura = LectorPdfUnificado(ocr=lambda imagen: TEXTO, vision=vision).leer(ruta)
    assert len(vision_llamadas) == 1
    assert factura.campos.nif.valor == "B12345678"
    assert factura.metodo.value == "ocr_determinista"


def test_metodo_distingue_texto_nativo_de_ocr_y_vision():
    """scan_013 y compañía: leídos por Firecrawl, no pueden salir como texto_determinista."""
    nativo = extraer_campos("a.pdf", [{"page": 1, "route": "native_text", "text": TEXTO}])
    assert nativo.metodo.value == "texto_determinista"
    ocr = extraer_campos("a.pdf", [{"page": 1, "route": "firecrawl_ocr", "text": TEXTO, "model": "firecrawl/parse"}])
    assert ocr.metodo.value == "ocr_determinista"
    mixto = extraer_campos("a.pdf", [
        {"page": 1, "route": "native_text", "text": TEXTO},
        {"page": 2, "route": "firecrawl_ocr", "text": "Gracias por su compra."},
    ])
    assert mixto.metodo.value == "ocr_determinista"
    vision = extraer_campos("a.pdf", [{"page": 1, "route": "vision_llm", "text": TEXTO}])
    assert vision.metodo.value == "vision_llm"


def test_vision_no_sustituye_un_ocr_caido(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    vision_llamadas = []

    def ocr(imagen):
        raise TimeoutError("timeout simulado")

    def vision(imagen):
        vision_llamadas.append(imagen)
        return TEXTO

    factura = LectorPdfUnificado(ocr=ocr, vision=vision).leer(ruta)
    assert factura.campos.nif.valor is None
    assert factura.errores
    assert vision_llamadas == []


def test_fallo_de_vision_conserva_el_ocr(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)

    def vision(imagen):
        raise LecturaFallida("API de visión no disponible")

    factura = LectorPdfUnificado(ocr=lambda imagen: "TOTAL 121,00 EUR", vision=vision).leer(ruta)
    assert factura.campos.total.valor == 121
    assert factura.campos.nif.valor is None
    assert any("visión" in error.lower() or "vision" in error.lower() for error in factura.errores)


def test_discrepancia_ocr_vision_no_elige_por_conveniencia(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    ocr = (
        "FACTURA FA-1001\nFecha 15 de enero de 2026\nPedido PO-2026-0001\n"
        "IBAN ES12 1234 1234 1234 1234 1234\nBase imponible 100,00 EUR\n"
        "IVA 21% 21,00 EUR\nTOTAL 200,00 EUR"
    )
    factura = LectorPdfUnificado(ocr=lambda imagen: ocr, vision=lambda imagen: TEXTO).leer(ruta)
    assert factura.campos.nif.valor == "B12345678"
    assert any("total" in error.lower() for error in factura.errores)


def test_vision_helmcode_transcribe_sin_fuentes():
    crear = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=TEXTO, refusal=None))],
    ))
    cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=crear)))
    texto = VisionHelmcode("k", "https://api.helmcode.com/v1", "qwen3.6", cliente=cliente)(b"png")
    assert texto == TEXTO.strip()
    enviados = crear.call_args.kwargs["messages"]
    assert "No calcules" in enviados[0]["content"]
    assert "maestro" not in enviados[1]["content"][0]["image_url"]["url"]


def test_adaptador_ocr_con_respuesta_simulada():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from upistas.adaptadores.lectores.firecrawl_ocr import FirecrawlOCR

    respuesta = SimpleNamespace(status_code=200, headers={},
                                json=Mock(return_value={"success": True, "data": {"markdown": TEXTO}}))
    ocr = FirecrawlOCR("fc-clave", cliente=SimpleNamespace(post=Mock(return_value=respuesta)))
    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20)).tobytes("png")
    assert ocr(png) == TEXTO.strip()
