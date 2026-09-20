from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pymupdf
import pytest
from openai import APITimeoutError

from upistas.adaptadores.lectores.campos import extraer_campos
from upistas.adaptadores.lectores.pdf_unificado import LectorPdfUnificado
from upistas.adaptadores.lectores.vision_helmcode import VisionHelmcode
from upistas.puertos import LecturaFallida

URL = "https://api.helmcode.com/v1"
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
    # Se leyó bien y no existe: no es un fallo de lectura, es un dato inválido que juzga la regla de la fecha.
    assert factura.campos.fecha.confianza == 1.0
    assert "31/02/2026" in factura.campos.fecha.fuente
    assert factura.errores == []


def test_mes_que_no_se_reconoce_es_fallo_de_lectura():
    factura = extraer(TEXTO.replace("15 de enero de 2026", "15 de encro de 2026"))
    assert factura.campos.fecha.valor is None
    assert factura.campos.fecha.confianza == 0.0
    assert "Valor inválido para la fecha" in factura.errores


def test_fecha_invalida_y_otra_valida_es_contradiccion():
    factura = extraer(TEXTO.replace("15 de enero de 2026", "31/02/2026") + "Fecha factura 01/04/2026")
    assert factura.campos.fecha.valor is None
    assert factura.campos.fecha.confianza == 0.0
    assert "La fecha aparece con dos valores: una fecha que no existe y 01/04/2026" in factura.errores


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
    assert factura.errores == ["Página 1: Escaneado: no hay lector de imagen disponible"]


def test_dos_valores_distintos_se_dicen_con_los_valores():
    factura = extraer(TEXTO.replace("NIF B12345678", "NIF B12345678\nNIF A41220987"))
    assert factura.campos.nif.valor is None
    assert "El NIF aparece con dos valores: B12345678 y A41220987" in factura.errores
    factura = extraer(TEXTO + "TOTAL 1.043,80 EUR\n")
    assert factura.campos.total.valor is None
    assert "El total aparece con dos valores: 121,00 y 1.043,80" in factura.errores


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


def test_vision_no_se_usa_si_el_ocr_ya_es_suficiente(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)

    def vision(imagen):
        pytest.fail("No debe llamarse a visión si el OCR ya tiene los campos")

    factura = LectorPdfUnificado(ocr=lambda imagen: TEXTO, vision=vision).leer(ruta)
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


def respuesta_vision(texto=TEXTO, tokens_in=0, tokens_out=0):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=texto, refusal=None))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


def cliente_vision(*respuestas):
    """Cliente OpenAI falso: cada llamada devuelve (o lanza) el siguiente elemento."""
    crear = Mock(side_effect=list(respuestas))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=crear)))


def test_fallo_pasajero_de_vision_no_se_cachea_y_conserva_el_ocr(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    ocr_llamadas = []

    def ocr(imagen):
        ocr_llamadas.append(imagen)
        return "FACTURA ILEGIBLE\nTOTAL 121,00 EUR"

    cliente = cliente_vision(APITimeoutError(request=httpx.Request("POST", URL)), respuesta_vision())
    lector = LectorPdfUnificado(ocr=ocr, vision=VisionHelmcode("k", URL, "qwen3.6", cliente=cliente), cache_dir=tmp_path / "cache")

    primera = lector.leer(ruta)
    assert primera.campos.total.valor == 121  # lo que el OCR sí leyó se conserva
    assert primera.campos.nif.valor is None
    assert any("visión" in error for error in primera.errores)

    segunda = lector.leer(ruta)  # la API vuelve: se reintenta la visión sin repetir el OCR
    assert segunda.campos.nif.valor == "B12345678"
    assert segunda.metodo.value == "vision_llm"
    assert segunda.errores == []
    assert len(ocr_llamadas) == 1
    assert cliente.chat.completions.create.call_count == 2

    assert lector.leer(ruta).campos.nif.valor == "B12345678"  # ahora sí vale la caché
    assert cliente.chat.completions.create.call_count == 2


def test_coste_acumula_ocr_y_vision_con_los_tokens_de_la_api(tmp_path):
    ruta = tmp_path / "scan.pdf"
    crear_pdf(ruta, None)
    vision = VisionHelmcode("k", URL, "qwen3.6", cliente=cliente_vision(respuesta_vision(tokens_in=1200, tokens_out=300)))
    class OcrFalso:
        modelo = "ocr-falso"

        def __call__(self, imagen):
            return "FACTURA ILEGIBLE" + chr(10) + "TOTAL 121,00 EUR"

    factura = LectorPdfUnificado(ocr=OcrFalso(), vision=vision).leer(ruta)
    assert factura.metodo.value == "vision_llm"
    assert factura.coste.modelo == "ocr-falso + qwen3.6"
    assert (factura.coste.tokens_in, factura.coste.tokens_out) == (1200, 300)


def test_coste_suma_los_tokens_de_todas_las_paginas():
    factura = extraer_campos("a.pdf", [
        {"page": 1, "route": "vision_llm", "text": TEXTO, "model": "qwen3.6", "modelo_ocr": "fal-ai/got-ocr/v2", "tokens_in": 1000, "tokens_out": 200},
        {"page": 2, "route": "vision_llm", "text": "Página 2 de 3", "model": "qwen3.6", "modelo_ocr": "fal-ai/got-ocr/v2", "tokens_in": 500, "tokens_out": 100},
        {"page": 3, "route": "fal_ocr", "text": "Página 3 de 3", "model": "fal-ai/got-ocr/v2"},
    ])
    assert factura.coste.modelo == "fal-ai/got-ocr/v2 + qwen3.6"
    assert (factura.coste.tokens_in, factura.coste.tokens_out) == (1500, 300)


def test_coste_solo_ocr_no_inventa_tokens_y_sin_ia_no_hay_coste():
    ocr = extraer_campos("a.pdf", [{"page": 1, "route": "fal_ocr", "text": TEXTO, "model": "fal-ai/got-ocr/v2"}])
    assert ocr.coste.modelo == "fal-ai/got-ocr/v2"
    assert (ocr.coste.tokens_in, ocr.coste.tokens_out) == (0, 0)
    assert extraer().coste is None


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


# --- Facturas internacionales del lote 2 (e0X) -------------------------------------------

EN = """INVOICE No.: INV-9102
Tax ID: A41220987
IBAN: ES76 2100 0813 6101 2345 6789
Issue date: 03 Feb 2026
Purchase Order: PO-2026-1303
Bill to: Banco Miralmar S.A.  ·  Tax ID: A58231074
Subtotal: € 780.00
VAT (21%): € 163.80
TOTAL: € 943.80 EUR
"""


def test_factura_en_ingles_en_euros_se_lee_entera():
    factura = extraer(EN)
    assert factura.campos.numero_factura.valor == "INV-9102"
    assert factura.campos.nif.valor == "A41220987"
    assert factura.campos.fecha.valor == "2026-02-03"
    assert factura.campos.pedido.valor == "PO-2026-1303"
    assert factura.campos.base.valor == 780
    assert factura.campos.iva.valor == 163.8
    assert factura.campos.total.valor == 943.8
    assert factura.campos.iban.valor == "ES7621000813610123456789"
    assert factura.errores == []


def test_el_cif_del_cliente_en_otro_idioma_no_es_un_nif_mas():
    factura = extraer(EN.replace("Bill to:", "Facturé à:"))
    assert factura.campos.nif.valor == "A41220987"  # un solo NIF, sin contradicción
    assert factura.errores == []


def test_sous_total_es_la_base_no_un_segundo_total():
    frances = EN.replace("Subtotal:", "Sous-total:").replace("INVOICE No.:", "FACTURE N°:") \
        .replace("Issue date:", "Date d'émission:").replace("VAT", "TVA")
    factura = extraer(frances)
    assert factura.campos.base.valor == 780
    assert factura.campos.total.valor == 943.8  # sin «Valores contradictorios para total»
    assert factura.campos.numero_factura.valor == "INV-9102"


def test_etiquetas_italianas_y_alemanas():
    italiano = EN.replace("Subtotal:", "Imponibile:").replace("TOTAL:", "TOTALE:") \
        .replace("Issue date:", "Data di emissione:").replace("INVOICE No.:", "FATTURA N.:")
    aleman = EN.replace("Subtotal:", "Zwischensumme:").replace("TOTAL:", "GESAMT:") \
        .replace("VAT (21%):", "MwSt. (21%):").replace("INVOICE No.:", "RECHNUNG Nr.:")
    for texto in (italiano, aleman):
        factura = extraer(texto)
        assert factura.campos.base.valor == 780
        assert factura.campos.total.valor == 943.8
        assert factura.campos.numero_factura.valor == "INV-9102"


@pytest.mark.parametrize("fecha,esperada", [
    ("dos de enero de dos mil veintiséis", "2026-01-02"),
    ("the seventh of March, two thousand twenty-six", "2026-03-07"),
    ("le trois janvier deux mille vingt-six", "2026-01-03"),
    ("sette agosto duemilaventisei", "2026-08-07"),
    ("am siebten März zweitausendsechsundzwanzig", "2026-03-07"),
    ("am fünfzehnten Juni zweitausendsechsundzwanzig", "2026-06-15"),
    ("dos de gener de dos mil vint-i-sis", "2026-01-02"),
    ("15 de fevereiro de 2026", "2026-02-15"),
    ("30/05/2026", "2026-05-30"),
])
def test_fechas_en_letra_en_cualquier_idioma(fecha, esperada):
    factura = extraer(EN.replace("03 Feb 2026", fecha))
    assert factura.campos.fecha.valor == esperada


def test_en_euros_la_divisa_es_eur_con_o_sin_marca():
    assert extraer(EN).campos.divisa.valor == "EUR"
    sin_marca = EN.replace("€ ", "").replace(" EUR", "")
    factura = extraer(sin_marca)
    assert factura.campos.divisa.valor == "EUR" and factura.campos.divisa.fuente is None
    assert factura.campos.total.valor == 943.8


def test_divisa_distinta_de_eur_se_lee_el_importe_y_la_divisa_es_un_campo():
    dolares = EN.replace("Subtotal: € 780.00", "Billing currency: USD ($)\nSubtotal: $ 2,450.00") \
        .replace("VAT (21%): € 163.80", "VAT (21%): $ 0.00").replace("TOTAL: € 943.80 EUR", "TOTAL: $ 2,450.00 USD")
    factura = extraer(dolares)
    assert factura.campos.total.valor == 2450  # se lee tal cual; compararlo con el pedido en euros es cosa de las reglas
    assert factura.campos.base.valor == 2450 and factura.campos.iva.valor == 0
    assert factura.campos.divisa.valor == "USD" and factura.campos.divisa.fuente == "Subtotal: $ 2,450.00"
    assert factura.errores == []
    assert factura.campos.fecha.valor == "2026-02-03"  # el resto se sigue leyendo


def test_divisa_declarada_y_yenes_sin_decimales():
    yenes = EN.replace("Issue date: 03 Feb 2026", "Fecha de emisión: 12/04/2026") \
        .replace("Subtotal: € 780.00", "Divisa de facturación: JPY (¥)\nBase imponible: ¥ 773,000") \
        .replace("VAT (21%): € 163.80", "IVA (21%): ¥ 77,000").replace("TOTAL: € 943.80 EUR", "TOTAL: ¥ 850,000 JPY")
    factura = extraer(yenes)
    assert factura.campos.divisa.valor == "JPY"
    assert factura.campos.base.valor == 773000 and factura.campos.iva.valor == 77000 and factura.campos.total.valor == 850000
    assert factura.errores == []


def test_dos_divisas_distintas_del_euro_en_la_misma_factura_es_un_error_de_lectura():
    mezcla = EN.replace("Subtotal: € 780.00", "Subtotal: $ 780.00").replace("TOTAL: € 943.80 EUR", "TOTAL: £ 943.80")
    factura = extraer(mezcla)
    assert "Importes en dos divisas: GBP y USD" in factura.errores
    assert factura.campos.divisa.valor is None and factura.campos.divisa.confianza == 0


def test_nif_e_iban_extranjeros_se_leen_etiquetados():
    aleman = EN.replace("Tax ID: A41220987", "USt-ID: DE812345678") \
        .replace("IBAN: ES76 2100 0813 6101 2345 6789", "IBAN: DE89 3704 0044 0532 0130 00")
    factura = extraer(aleman)
    assert factura.campos.nif.valor == "DE812345678"
    assert factura.campos.iban.valor == "DE89370400440532013000"


def test_payment_terms_en_otro_idioma_va_a_notas():
    aleman = EN + "Zahlungsbedingungen: 30 Tage ab Ausstellungsdatum.\n"
    factura = extraer(aleman)
    assert any("Zahlungsbedingungen" in n.texto for n in factura.notas)
