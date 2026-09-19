"""Versiones de los datos de referencia y qué cambia entre ellas.

La versión es una huella del contenido: dos descargas con los mismos asientos tienen la misma
versión aunque lleguen en otro orden. Así sabemos si el ERP ha cambiado (lote 2, el dato del
domingo) y qué decisiones hay que revisar.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from upistas.dominio.modelos import Asiento

CAMPOS = ("pedido", "proveedor_id", "nif", "importe", "fecha", "estado")


def _fila(a: Asiento) -> str:
    fecha = a.fecha.isoformat() if a.fecha else ""
    return "|".join((a.id, a.pedido, a.proveedor_id, a.nif, f"{a.importe:.2f}", fecha, a.estado))


def version_asientos(asientos: Iterable[Asiento]) -> str:
    huella = hashlib.sha256()
    for fila in sorted(_fila(a) for a in asientos):
        huella.update(fila.encode("utf-8"))
        huella.update(b"\n")
    return huella.hexdigest()[:12]


@dataclass(frozen=True)
class Cambio:
    asiento: str
    campo: str
    antes: str
    despues: str


@dataclass(frozen=True)
class Diferencias:
    nuevos: tuple[str, ...] = ()  # ids de asiento
    eliminados: tuple[str, ...] = ()
    modificados: tuple[Cambio, ...] = field(default_factory=tuple)
    pedidos_afectados: frozenset[str] = frozenset()  # facturas de estos pedidos hay que volver a decidir

    @property
    def vacias(self) -> bool:
        return not (self.nuevos or self.eliminados or self.modificados)


def diferencias(antes: Iterable[Asiento], despues: Iterable[Asiento]) -> Diferencias:
    a = {x.id: x for x in antes}
    d = {x.id: x for x in despues}
    modificados = []
    pedidos: set[str] = set()
    for asiento_id in sorted(a.keys() & d.keys()):
        for campo in CAMPOS:
            va, vd = getattr(a[asiento_id], campo), getattr(d[asiento_id], campo)
            if va != vd:
                modificados.append(Cambio(asiento_id, campo, str(va), str(vd)))
                pedidos.update((a[asiento_id].pedido, d[asiento_id].pedido))
    nuevos, eliminados = sorted(d.keys() - a.keys()), sorted(a.keys() - d.keys())
    pedidos.update(d[i].pedido for i in nuevos)
    pedidos.update(a[i].pedido for i in eliminados)
    return Diferencias(
        nuevos=tuple(nuevos),
        eliminados=tuple(eliminados),
        modificados=tuple(modificados),
        pedidos_afectados=frozenset(pedidos),
    )
