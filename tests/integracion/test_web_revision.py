"""La cola de lo que Alberto tiene que mirar y lo que decide sobre cada factura escalada."""
import pytest
from django.urls import reverse

from web.panel.models import RevisionHumana

pytestmark = pytest.mark.django_db

ESCALADA = "2026-07-01_P009.pdf"
ESCANEADA = "scan_001.pdf"


def cola(alberto, **filtros) -> str:
    return alberto.get(reverse("panel:cola"), filtros).content.decode()


def url_revisar(file_id: str, lote: str = "lote1") -> str:
    return reverse("panel:revisar", args=[lote, file_id])


def test_la_cola_ensena_las_pendientes_con_su_motivo(alberto, lote_de_prueba):
    html = cola(alberto)
    assert ESCALADA in html and ESCANEADA in html
    assert "FA-1016" not in html  # las que ya decidió el sistema no le molestan
    assert "Importe fuera de lo habitual: 84700.00 €" in html
    assert "ningún lector acepta un documento de tipo escaneado" in html
    # Agrupadas por el motivo principal, en palabras, y con lo leído de la factura.
    assert "Sin texto que intente influir en la decisión" in html and "No se pudo leer" in html
    assert "Construcciones Benimaclet S.A." in html and "84.700,00 €" in html
    assert "Ver el PDF" in html
    assert "<b>2</b><span>Pendientes de revisar</span>" in html


def test_los_filtros_separan_lo_pendiente_de_lo_ya_revisado(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][ESCALADA]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="alberto", resultado="PAGAR")

    pendientes = cola(alberto)
    assert ESCANEADA in pendientes and ESCALADA not in pendientes
    revisadas = cola(alberto, estado="revisadas")
    assert ESCALADA in revisadas and ESCANEADA not in revisadas
    todas = cola(alberto, estado="todas")
    assert ESCALADA in todas and ESCANEADA in todas


def test_la_busqueda_encuentra_por_fichero_pedido_y_motivo(alberto, lote_de_prueba):
    assert ESCANEADA in cola(alberto, q="scan") and ESCALADA not in cola(alberto, q="scan")
    assert ESCALADA in cola(alberto, q="PO-2026-0497")
    assert ESCALADA in cola(alberto, q="importe fuera")
    assert "Ninguna factura coincide con lo que ha escrito." in cola(alberto, q="no existe nada asi")


def test_con_htmx_la_cola_devuelve_solo_la_lista(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:cola"), HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in html and "Pendientes de revisar" not in html
    assert ESCALADA in html and ESCANEADA in html


def test_pagar_guarda_la_revision_y_saca_la_factura_de_pendientes(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][ESCALADA]
    respuesta = alberto.post(url_revisar(ESCALADA), {"resultado": "PAGAR", "comentario": "Obra certificada"})

    assert respuesta.status_code == 302
    revision = RevisionHumana.objects.get()
    assert revision.quien == "alberto" and revision.resultado == "PAGAR"
    assert revision.documento_id == d.documento_id and revision.decision_id == d.id
    assert revision.comentario == "Obra certificada"
    assert "Guardado: 2026-07-01_P009.pdf queda como «Pagar»." in cola(alberto)
    pendientes = alberto.get(reverse("panel:cola"), HTTP_HX_REQUEST="true").content.decode()
    assert ESCALADA not in pendientes and ESCANEADA in pendientes


def test_con_htmx_la_decision_vuelve_como_un_trozo_de_pagina(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][ESCALADA]
    respuesta = alberto.post(
        url_revisar(ESCALADA), {"resultado": "PAGAR", "comentario": "Obra certificada"}, HTTP_HX_REQUEST="true"
    )
    html = respuesta.content.decode()

    assert respuesta.status_code == 200 and "<html" not in html
    assert f'id="revision-{d.id}"' in html
    assert '<span class="pildora bien">Pagar</span>' in html
    assert "«Obra certificada»" in html and "alberto" in html


def test_sin_htmx_vuelve_al_detalle_de_la_factura(alberto, lote_de_prueba):
    respuesta = alberto.post(url_revisar(ESCALADA), {"resultado": "NO_PAGAR", "comentario": ""})
    assert respuesta.headers["Location"] == reverse("panel:factura", args=["lote1", ESCALADA])


def test_una_decision_que_no_vale_no_se_guarda(alberto, lote_de_prueba):
    assert alberto.post(url_revisar(ESCALADA), {"resultado": "QUIZA"}).status_code == 400
    assert alberto.post(url_revisar(ESCALADA), {"comentario": "sin decidir"}).status_code == 400
    largo = alberto.post(url_revisar(ESCALADA), {"resultado": "PAGAR", "comentario": "x" * 501})
    assert largo.status_code == 400 and "500" in largo.content.decode()
    assert not RevisionHumana.objects.exists()


def test_una_factura_que_no_existe_da_404(alberto, lote_de_prueba):
    assert alberto.post(url_revisar("no_existe.pdf"), {"resultado": "PAGAR"}).status_code == 404
    assert alberto.post(url_revisar(ESCALADA, lote="lote9"), {"resultado": "PAGAR"}).status_code == 404


def test_la_insignia_de_la_cabecera_baja_al_revisar(alberto, lote_de_prueba):
    insignia = '<span class="insignia" title="Pendientes de revisar">{}</span>'
    assert insignia.format(2) in cola(alberto)
    alberto.post(url_revisar(ESCANEADA), {"resultado": "NO_PAGAR", "comentario": "No se lee, la pido otra vez"})
    assert insignia.format(1) in cola(alberto)


def test_puede_revisar_dos_veces_y_manda_la_ultima(alberto, lote_de_prueba):
    alberto.post(url_revisar(ESCALADA), {"resultado": "PAGAR", "comentario": "La pago"})
    alberto.post(url_revisar(ESCALADA), {"resultado": "NO_PAGAR", "comentario": "Mejor no, falta el albaran"})

    assert RevisionHumana.objects.count() == 2  # el historial no se borra
    revisadas = cola(alberto, estado="revisadas")
    assert "Mejor no, falta el albaran" in revisadas and "La pago" not in revisadas
    assert '<span class="pildora mal">No pagar</span>' in revisadas
    assert "No hay nada pendiente de revisar" not in revisadas and ESCANEADA in cola(alberto)
