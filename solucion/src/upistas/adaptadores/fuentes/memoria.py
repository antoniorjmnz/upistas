"""Fuentes en memoria: para tests y para arrancar antes de tener Excel y ERP conectados."""
from __future__ import annotations

from dataclasses import dataclass, field

from upistas.dominio.modelos import Asiento, Pedido, Proveedor
from upistas.puertos import Sincronizacion


@dataclass
class MaestroEnMemoria:
    lista_proveedores: list[Proveedor] = field(default_factory=list)
    lista_pedidos: list[Pedido] = field(default_factory=list)
    marcados: frozenset[str] = frozenset()
    version: str = "memoria"

    def proveedores(self) -> list[Proveedor]:
        return self.lista_proveedores

    def pedidos(self) -> list[Pedido]:
        return self.lista_pedidos

    def marcados_para_revisar(self) -> frozenset[str]:
        return self.marcados


@dataclass
class ErpEnMemoria:
    lista_asientos: list[Asiento] = field(default_factory=list)

    def asientos(self) -> list[Asiento]:
        return self.lista_asientos


@dataclass
class AlmacenERPEnMemoria:
    versiones: dict[str, tuple[Asiento, ...]] = field(default_factory=dict)
    historial: list[Sincronizacion] = field(default_factory=list)

    def registrar(self, sincronizacion: Sincronizacion, asientos: tuple[Asiento, ...] | None) -> None:
        if sincronizacion.ok and sincronizacion.version and asientos is not None:
            self.versiones.setdefault(sincronizacion.version, tuple(asientos))
        self.historial.append(sincronizacion)

    def asientos(self, version: str | None = None) -> list[Asiento]:
        if version is None:
            ultima = self.ultima()
            version = ultima.version if ultima else None
        return list(self.versiones.get(version, ())) if version else []

    def ultima(self, solo_correctas: bool = True) -> Sincronizacion | None:
        for s in reversed(self.historial):
            if s.ok or not solo_correctas:
                return s
        return None
