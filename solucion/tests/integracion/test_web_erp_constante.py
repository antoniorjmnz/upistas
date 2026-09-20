"""La sincronización constante con el ERP: el interruptor, el vigilante que trae el ERP cada minuto y lo que se ve."""
import threading
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.modelos import Asiento
from upistas.puertos import DescargaERP, EstadisticasDescarga
from web.panel import sincronizacion
from web.panel.models import Ajuste, SincronizacionERP

pytestmark = pytest.mark.django_db

BASE = Asiento("AS-00084", "PO-2026-0084", "P002", "A41220987", Decimal("6199.54"), date(2026, 3, 21), "PENDIENTE")
LOTE = (BASE, replace(BASE, id="AS-00474", pedido="PO-2026-0474", proveedor_id="P007", nif="J40112358", estado="PAGADA"))
CAMBIADO = (BASE, replace(LOTE[1], estado="PENDIENTE"))


class Cliente:
    """ClienteERP de mentira: devuelve, por orden, las descargas que le pasen; sin red."""

    def __init__(self, *descargas):
        self.descargas = list(descargas)

    def descargar(self):
        return DescargaERP(asientos=self.descargas.pop(0), lote2_cargado=False, estadisticas=EstadisticasDescarga(peticiones=30, segundos=3.9))


@pytest.fixture
def con_copia():
    return sincronizar_erp(Cliente(LOTE), AlmacenERPDjango())


def test_el_interruptor_se_guarda_y_vuelve_marcado(alberto):
    assert "Mantener la sincronización constante" in alberto.get(reverse("panel:conexion")).content.decode()
    r = alberto.post(reverse("panel:constante"), {"activa": "1"}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert r.status_code == 200 and "<html" not in html  # solo el fragmento para htmx
    assert Ajuste.leer("erp_constante") == "1" and sincronizacion.esta_activa()
    assert 'name="activa" value="1" checked' in html
    r = alberto.post(reverse("panel:constante"), {}, HTTP_HX_REQUEST="true")  # desmarcado: el checkbox no viaja
    assert not sincronizacion.esta_activa() and 'name="activa" value="1" checked' not in r.content.decode()
    assert alberto.post(reverse("panel:constante"), {"activa": "1"}).status_code == 302  # sin htmx, recarga la pantalla


def test_las_automaticas_se_marcan_y_las_del_boton_no(alberto, monkeypatch):
    from upistas.infra import contenedor

    monkeypatch.setattr(contenedor, "cliente_erp", lambda: Cliente(LOTE, LOTE))
    assert sincronizacion.sincronizar_una_vez().ok
    assert SincronizacionERP.objects.get().automatica is True
    alberto.post(reverse("panel:sincronizar"))
    assert [s.automatica for s in SincronizacionERP.objects.order_by("id")] == [True, False]


def test_toca_sincronizar_solo_si_esta_activa_y_la_ultima_es_vieja(con_copia):
    ahora = timezone.now()
    assert not sincronizacion.toca_sincronizar(ahora)  # desactivada
    sincronizacion.activar(True)
    assert not sincronizacion.toca_sincronizar(ahora)  # la copia es de ahora mismo
    assert sincronizacion.toca_sincronizar(ahora + timedelta(seconds=sincronizacion.CADA_S + 1))
    SincronizacionERP.objects.create(inicio=ahora, fin=ahora, ok=False, error="ORA-00600")
    assert not sincronizacion.toca_sincronizar(ahora + timedelta(seconds=5))  # una fallida reciente también cuenta
    SincronizacionERP.objects.all().delete()
    assert sincronizacion.toca_sincronizar(ahora)  # sin ninguna, toca


def test_el_historial_no_se_llena_de_comprobaciones_automaticas(alberto, con_copia):
    for descarga in (LOTE, LOTE, CAMBIADO):
        sincronizar_erp(Cliente(descarga), AlmacenERPDjango(automatica=True))
    html = alberto.get(reverse("panel:conexion")).content.decode()
    assert "2 comprobaciones automáticas sin cambios (la última " in html
    assert html.count('<span class="pildora bien">Correcta</span>') == 2  # la primera copia y la automática con cambios
    assert "automática</span>" in html and "1 modificados" in html


def test_el_vigilante_no_arranca_bajo_pytest(monkeypatch):
    monkeypatch.delenv("RUN_MAIN", raising=False)
    assert sincronizacion.arrancar_si_procede() is False
    assert not any(h.name == "erp-constante" for h in threading.enumerate())


def test_la_barra_lateral_dice_que_la_sincronizacion_es_constante(alberto, con_copia):
    url = reverse("panel:asientos")  # cualquier pantalla: la barra lateral está en todas
    assert "<small>sincronización constante</small>" not in alberto.get(url).content.decode()
    sincronizacion.activar(True)
    html = alberto.get(url).content.decode()
    assert 'class="estado-erp bien viva"' in html and "<small>sincronización constante</small>" in html
