from dataclasses import replace
from datetime import date
from decimal import Decimal

from upistas.dominio.modelos import Asiento
from upistas.dominio.versiones import diferencias, version_asientos


def asiento(n: int, **cambios) -> Asiento:
    base = Asiento(f"AS-{n:05d}", f"PO-2026-{n:04d}", "P001", "B46102331", Decimal("100.00"), date(2026, 1, 8), "PENDIENTE")
    return replace(base, **cambios)


def test_la_version_no_depende_del_orden():
    a = [asiento(1), asiento(2), asiento(3)]
    assert version_asientos(a) == version_asientos(list(reversed(a)))


def test_cualquier_cambio_cambia_la_version():
    a = [asiento(1), asiento(2)]
    b = [asiento(1), asiento(2, estado="PAGADA")]
    assert version_asientos(a) != version_asientos(b)


def test_diferencias_detecta_nuevos_eliminados_y_modificados():
    antes = [asiento(1), asiento(2), asiento(3)]
    despues = [asiento(1), asiento(2, estado="PAGADA", importe=Decimal("90.00")), asiento(4)]
    d = diferencias(antes, despues)
    assert d.nuevos == ("AS-00004",)
    assert d.eliminados == ("AS-00003",)
    assert {(c.asiento, c.campo) for c in d.modificados} == {("AS-00002", "estado"), ("AS-00002", "importe")}
    assert d.pedidos_afectados == {"PO-2026-0002", "PO-2026-0003", "PO-2026-0004"}


def test_sin_cambios_no_hay_diferencias():
    a = [asiento(1), asiento(2)]
    assert diferencias(a, list(reversed(a))).vacias


def test_pedidos_afectados_usa_el_pedido_no_el_asiento():
    # En el ERP real el asiento AS-00507 es el pedido PO-2026-0546.
    antes = [asiento(507, pedido="PO-2026-0546")]
    despues = [asiento(507, pedido="PO-2026-0546", estado="PAGADA")]
    assert diferencias(antes, despues).pedidos_afectados == {"PO-2026-0546"}
