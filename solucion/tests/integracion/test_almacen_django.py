from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.modelos import Asiento
from upistas.puertos import DescargaERP, ErrorERP, EstadisticasDescarga

pytestmark = pytest.mark.django_db

BASE = Asiento("AS-00001", "PO-2026-0001", "P001", "B46102331", Decimal("1512.50"), date(2026, 1, 8), "PENDIENTE")


def lote(estado_2="PENDIENTE"):
    return (BASE, replace(BASE, id="AS-00507", pedido="PO-2026-0546", nif="", estado=estado_2))


class Cliente:
    def __init__(self, *r):
        self.r = list(r)

    def descargar(self):
        x = self.r.pop(0)
        if isinstance(x, Exception):
            raise x
        return DescargaERP(asientos=x, lote2_cargado=False, estadisticas=EstadisticasDescarga(peticiones=30, reintentos_ora=3))


def reloj():
    return datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)


def test_guarda_y_recupera_los_asientos_tal_cual():
    almacen = AlmacenERPDjango()
    s = sincronizar_erp(Cliente(lote()), almacen, reloj)
    recuperados = {a.id: a for a in almacen.asientos()}
    assert recuperados["AS-00001"] == BASE
    assert recuperados["AS-00507"].nif == ""
    assert almacen.ultima().version == s.version
    assert almacen.ultima().estadisticas.reintentos_ora == 3


def test_misma_version_no_duplica_asientos():
    from web.panel.models import AsientoERP, SincronizacionERP, VersionERP

    almacen = AlmacenERPDjango()
    sincronizar_erp(Cliente(lote(), lote()), almacen, reloj)
    sincronizar_erp(Cliente(lote()), almacen, reloj)
    assert VersionERP.objects.count() == 1
    assert AsientoERP.objects.count() == 2
    assert SincronizacionERP.objects.count() == 2


def test_version_nueva_guarda_los_cambios_y_conserva_la_anterior():
    from web.panel.models import VersionERP

    almacen = AlmacenERPDjango()
    a = sincronizar_erp(Cliente(lote()), almacen, reloj)
    b = sincronizar_erp(Cliente(lote(estado_2="PAGADA")), almacen, reloj)
    assert b.modificados == 1
    assert VersionERP.objects.count() == 2
    assert {x.estado for x in almacen.asientos(a.version)} == {"PENDIENTE"}
    assert "PAGADA" in {x.estado for x in almacen.asientos()}


def test_un_fallo_queda_registrado_sin_perder_la_copia():
    almacen = AlmacenERPDjango()
    buena = sincronizar_erp(Cliente(lote()), almacen, reloj)
    sincronizar_erp(Cliente(ErrorERP("El ERP no responde")), almacen, reloj)
    assert almacen.ultima(solo_correctas=False).ok is False
    assert almacen.ultima().version == buena.version
    assert len(almacen.asientos()) == 2
