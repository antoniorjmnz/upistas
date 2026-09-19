"""Las facturas de Alberto: la lista con sus filtros, el detalle con toda la traza y el PDF original."""
import pytest
from django.urls import reverse

from web.panel.models import RevisionHumana

pytestmark = pytest.mark.django_db

P009 = "2026-07-01_P009.pdf"
FA1016 = "FA-1016_papelería.pdf"


def pagina(alberto, **filtros) -> str:
    return alberto.get(reverse("panel:facturas"), filtros).content.decode()


def test_la_lista_ensena_las_cinco_con_su_pildora_y_su_total(alberto, lote_de_prueba):
    html = pagina(alberto)
    for file_id in lote_de_prueba["documentos"]:
        assert file_id in html
    assert "2.490,00 €" in html and "84.700,00 €" in html and "1.210,00 €" in html
    assert 'class="pildora bien">Pagar' in html
    assert 'class="pildora mal">No pagar' in html
    assert 'class="pildora ojo">Revisar' in html
    assert "Construcciones Benimaclet S.A." in html and "08/01/2026" in html  # la fecha leída, en español
    assert "avisos" in html and "texto raro" in html


def test_la_lista_aguanta_sin_ningun_lote(alberto):
    assert "Todavía no hemos pasado ningún lote" in pagina(alberto)


def test_filtrar_por_resultado(alberto, lote_de_prueba):
    html = pagina(alberto, resultado="NO_PAGAR")
    assert FA1016 in html
    assert "2026-01-08_P001.pdf" not in html and P009 not in html
    assert "1 de 5 facturas" in html


def test_filtrar_por_revision(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][P009]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="alberto", resultado="PAGAR")

    revisadas = pagina(alberto, revision="revisadas")
    assert P009 in revisadas and "scan_001.pdf" not in revisadas

    pendientes = pagina(alberto, revision="pendientes")
    assert "scan_001.pdf" in pendientes and P009 not in pendientes
    assert "4 de 5 facturas" in pendientes


def test_buscar_por_proveedor_y_por_pedido(alberto, lote_de_prueba):
    por_proveedor = pagina(alberto, q="Benimaclet")
    assert P009 in por_proveedor and FA1016 not in por_proveedor

    por_pedido = pagina(alberto, q="0474")
    assert FA1016 in por_pedido and P009 not in por_pedido


def test_con_htmx_solo_viene_la_tabla(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:facturas"), HTTP_HX_REQUEST="true").content.decode()
    assert "<table" in html and P009 in html
    assert "<html" not in html and "Salir" not in html


def test_el_detalle_ensena_toda_la_traza(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:factura", args=["lote1", P009])).content.decode()

    # Las reglas que fallan, con su nombre en palabras de Alberto.
    assert "Importe dentro de lo habitual" in html
    assert "Sin texto que intente influir en la decisión" in html
    assert "Importe fuera de lo habitual: 84700.00 € (umbral 20000 €)" in html

    # El texto que no decide, traducido.
    assert "PAGO INMEDIATO" in html and "mete prisa" in html
    assert "Lo que dice una factura nunca decide" in html

    # Los campos leídos con su confianza y el fichero.
    assert "seguridad 90 %" in html and "seguridad 100 %" in html
    assert lote_de_prueba["documentos"][P009].sha256 in html

    # El historial con las dos ejecuciones, y el formulario para decidir.
    assert lote_de_prueba["ejecucion"].version_datos in html
    assert lote_de_prueba["anterior"].version_datos in html
    assert f'id="revision-{lote_de_prueba["decisiones"][P009].id}"' in html


def test_el_detalle_de_un_escaneado_explica_que_no_se_pudo_leer(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:factura", args=["lote1", "scan_001.pdf"])).content.decode()
    assert "No hemos podido comprobar ninguna norma" in html  # no hay reglas que enseñar
    assert "No se pudo leer la factura (ningún lector acepta" in html  # el motivo, tal cual
    assert "no aparece" in html  # los campos vacíos
    assert "Escaneado: es una foto, no tiene texto" in html


def test_el_historial_ensena_que_antes_se_pagaba(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:factura", args=["lote1", FA1016])).content.decode()
    assert '<span class="pildora bien">Pagar</span>' in html
    assert '<span class="pildora mal">No pagar</span>' in html
    assert "El pedido PO-2026-0474 ya está pagado según el ERP" in html


def test_el_detalle_de_una_factura_que_no_existe_da_404(alberto, lote_de_prueba):
    assert alberto.get(reverse("panel:factura", args=["lote1", "inventada.pdf"])).status_code == 404


def test_el_pdf_da_404_si_el_fichero_ya_no_esta(alberto, lote_de_prueba):
    assert alberto.get(reverse("panel:factura_pdf", args=["lote1", P009])).status_code == 404


def test_el_pdf_se_sirve_en_linea(alberto, lote_de_prueba, tmp_path):
    import pymupdf

    ruta = tmp_path / "factura.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.save(ruta)
    documento.close()

    guardado = lote_de_prueba["documentos"][P009]
    guardado.ruta = str(ruta)
    guardado.save(update_fields=["ruta"])

    respuesta = alberto.get(reverse("panel:factura_pdf", args=["lote1", P009]))
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    assert "attachment" not in respuesta.get("Content-Disposition", "")
    assert b"".join(respuesta.streaming_content).startswith(b"%PDF")
