from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from upistas.adaptadores.fuentes.memoria import AlmacenERPEnMemoria
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.modelos import Asiento
from upistas.puertos import DescargaERP, ErrorERP, EstadisticasDescarga


def asientos(estado_2="PENDIENTE"):
    base = Asiento("AS-00001", "PO-2026-0001", "P001", "B46102331", Decimal("100.00"), date(2026, 1, 8), "PENDIENTE")
    return (base, replace(base, id="AS-00002", pedido="PO-2026-0002", estado=estado_2))


class ClienteFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)

    def descargar(self):
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return DescargaERP(asientos=r, lote2_cargado=False, estadisticas=EstadisticasDescarga(peticiones=3))


def reloj():
    return datetime(2026, 9, 19, 10, 0)


def test_primera_sincronizacion_guarda_la_version():
    almacen = AlmacenERPEnMemoria()
    s = sincronizar_erp(ClienteFalso(asientos()), almacen, reloj)
    assert s.ok and s.n_asientos == 2 and s.version
    assert len(almacen.asientos()) == 2


def test_sin_cambios_misma_version_y_no_duplica():
    almacen = AlmacenERPEnMemoria()
    a = sincronizar_erp(ClienteFalso(asientos()), almacen, reloj)
    b = sincronizar_erp(ClienteFalso(tuple(reversed(asientos()))), almacen, reloj)
    assert a.version == b.version
    assert len(almacen.versiones) == 1
    assert (b.nuevos, b.modificados, b.eliminados) == (0, 0, 0)


def test_si_el_erp_cambia_nueva_version_con_los_cambios():
    almacen = AlmacenERPEnMemoria()
    a = sincronizar_erp(ClienteFalso(asientos()), almacen, reloj)
    b = sincronizar_erp(ClienteFalso(asientos(estado_2="PAGADA")), almacen, reloj)
    assert a.version != b.version
    assert b.modificados == 1
    assert {x.estado for x in almacen.asientos()} == {"PENDIENTE", "PAGADA"}


def test_si_el_erp_falla_se_registra_y_se_sigue_con_la_copia_anterior():
    almacen = AlmacenERPEnMemoria()
    buena = sincronizar_erp(ClienteFalso(asientos()), almacen, reloj)
    mala = sincronizar_erp(ClienteFalso(ErrorERP("bridge caído")), almacen, reloj)
    assert not mala.ok and "caído" in mala.error
    assert almacen.ultima().version == buena.version
    assert almacen.ultima(solo_correctas=False) is mala
    assert len(almacen.asientos()) == 2
