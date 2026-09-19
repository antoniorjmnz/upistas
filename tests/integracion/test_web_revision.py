"""Para revisar: lo que Alberto tiene que decidir, agrupado por el motivo, y lo que decide sobre cada factura."""
import pytest
from django.urls import reverse

from web.panel.models import RevisionHumana

pytestmark = pytest.mark.django_db

ESCALADA = "2026-07-01_P009.pdf"
ESCANEADA = "scan_001.pdf"
NOTAS = "Trae texto que intenta influir en la decisión"
SIN_LEER = "No se pudo leer la factura"


def cola(alberto, **filtros) -> str:
    return alberto.get(reverse("panel:cola"), filtros).content.decode()


def url_revisar(file_id: str, lote: str = "lote1") -> str:
    return reverse("panel:revisar", args=[lote, file_id])


def decidir(alberto, file_id: str, resultado: str, comentario: str = "", **extra):
    return alberto.post(url_revisar(file_id), {"resultado": resultado, "comentario": comentario}, **extra)


def test_dice_cuantas_esperan_y_cuanto_lleva_decidido(alberto, lote_de_prueba):
    html = cola(alberto)
    assert "2 facturas esperan su decisión" in html
    assert "Solo le pasamos las que el sistema no puede resolver con seguridad" in html
    assert "0 de 2 decididas" in html
    assert "Pendientes (2)" in html and "Decididas (0)" in html


def test_las_agrupa_por_el_motivo_dicho_en_palabras(alberto, lote_de_prueba):
    html = cola(alberto)
    assert f"<h2>{NOTAS}</h2>" in html and f"<h2>{SIN_LEER}</h2>" in html
    assert "Construcciones Benimaclet S.A." in html and "84.700,00 €" in html
    assert "FA-1016" not in html  # lo que el sistema ya decidió no le molesta
    assert "R6_notas" not in html and "umbral" not in html  # ni ids ni jerga


def test_cada_factura_lleva_a_su_detalle_y_a_su_pdf(alberto, lote_de_prueba):
    html = cola(alberto)
    assert "Ver la factura" in html and "Ver el PDF" in html
    assert reverse("panel:factura", args=["lote1", ESCALADA]) in html
    assert reverse("panel:factura_pdf", args=["lote1", ESCALADA]) in html
    assert reverse("panel:factura_pdf", args=["lote1", ESCANEADA]) in html


def test_los_chips_separan_lo_pendiente_de_lo_ya_decidido(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][ESCALADA]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="Alberto", resultado="PAGAR")

    pendientes = cola(alberto)
    assert ESCANEADA in pendientes and ESCALADA not in pendientes
    assert "Pendientes (1)" in pendientes and "Decididas (1)" in pendientes and "1 de 2 decididas" in pendientes
    decididas = cola(alberto, estado="decididas")
    assert ESCALADA in decididas and ESCANEADA not in decididas
    assert '<a class="chip activa" href="?estado=decididas' in decididas  # se ve cuál está mirando


def test_la_busqueda_encuentra_por_fichero_pedido_y_motivo(alberto, lote_de_prueba):
    assert ESCANEADA in cola(alberto, q="scan") and ESCALADA not in cola(alberto, q="scan")
    assert ESCALADA in cola(alberto, q="PO-2026-0497")
    assert ESCALADA in cola(alberto, q="importe fuera")
    assert "No hay ninguna factura con eso" in cola(alberto, q="no existe nada asi")


def test_con_htmx_solo_vuelve_la_lista(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:cola"), HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in html and "esperan su decisión" not in html and "0 de 2 decididas" not in html
    assert ESCALADA in html and ESCANEADA in html and NOTAS in html
    assert 'hx-swap-oob="outerHTML"' in html  # los chips vuelven con ella para quedarse al día


def test_pagar_guarda_la_decision_a_nombre_de_alberto(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][ESCALADA]
    respuesta = decidir(alberto, ESCALADA, "PAGAR", "Obra certificada")

    assert respuesta.status_code == 302
    assert respuesta.headers["Location"] == reverse("panel:factura", args=["lote1", ESCALADA])
    revision = RevisionHumana.objects.get()
    assert revision.quien == "Alberto" and revision.resultado == "PAGAR" and revision.comentario == "Obra certificada"
    assert revision.documento_id == d.documento_id and revision.decision_id == d.id
    assert "Guardado: 2026-07-01_P009.pdf queda como «Pagar»." in cola(alberto)


def test_con_htmx_la_decision_vuelve_con_la_pildora_grande(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][ESCALADA]
    respuesta = decidir(alberto, ESCALADA, "PAGAR", "Obra certificada", HTTP_HX_REQUEST="true")
    html = respuesta.content.decode()

    assert respuesta.status_code == 200 and "<html" not in html
    assert f'id="revision-{d.id}"' in html
    assert 'class="pildora grande bien"' in html and "Pagar</span>" in html
    assert "«Obra certificada»" in html and "Lo decidió usted" in html
    assert "Cambiar la decisión" in html  # puede rectificar, pero plegado


def test_lo_que_acaba_de_decidir_sigue_a_la_vista_hasta_que_recarga(alberto, lote_de_prueba):
    trozo = decidir(alberto, ESCALADA, "PAGAR", HTTP_HX_REQUEST="true").content.decode()
    assert "Lo decidió usted" in trozo
    assert "<li>" not in trozo and NOTAS not in trozo  # solo cambia ese trozo: la factura se queda en la lista
    assert ESCALADA not in cola(alberto)  # al recargar ya no le vuelve a salir


def test_una_decision_que_no_vale_no_se_guarda(alberto, lote_de_prueba):
    assert alberto.post(url_revisar(ESCALADA), {"resultado": "QUIZA"}).status_code == 400
    assert alberto.post(url_revisar(ESCALADA), {"comentario": "sin decidir"}).status_code == 400
    largo = alberto.post(url_revisar(ESCALADA), {"resultado": "PAGAR", "comentario": "x" * 501})
    assert largo.status_code == 400 and "500" in largo.content.decode()
    assert not RevisionHumana.objects.exists()


def test_una_factura_que_no_existe_da_404(alberto, lote_de_prueba):
    assert alberto.post(url_revisar("no_existe.pdf"), {"resultado": "PAGAR"}).status_code == 404
    assert alberto.post(url_revisar(ESCALADA, lote="lote9"), {"resultado": "PAGAR"}).status_code == 404


def test_la_insignia_de_la_cabecera_baja_al_decidir(alberto, lote_de_prueba):
    insignia = '<span class="insignia" title="Pendientes de revisar">{}</span>'
    assert insignia.format(2) in cola(alberto)
    decidir(alberto, ESCANEADA, "NO_PAGAR", "No se lee, la pido otra vez")
    assert insignia.format(1) in cola(alberto)


def test_puede_decidir_dos_veces_y_manda_la_ultima(alberto, lote_de_prueba):
    decidir(alberto, ESCALADA, "PAGAR", "La pago")
    decidir(alberto, ESCALADA, "NO_PAGAR", "Mejor no, falta el albaran")

    assert RevisionHumana.objects.count() == 2  # el historial no se borra
    decididas = cola(alberto, estado="decididas")
    assert "Mejor no, falta el albaran" in decididas and "La pago" not in decididas
    assert 'class="pildora grande mal"' in decididas and "No pagar</span>" in decididas
    assert ESCANEADA in cola(alberto)  # la otra sigue esperando


def test_cuando_todo_esta_decidido_se_lo_dice(alberto, lote_de_prueba):
    for file_id in (ESCALADA, ESCANEADA):
        decidir(alberto, file_id, "NO_PAGAR")
    html = cola(alberto)

    assert "No hay nada esperando su decisión" in html and "2 de 2 decididas" in html
    assert '<div class="vacio">' in html and "No le queda nada por decidir" in html
