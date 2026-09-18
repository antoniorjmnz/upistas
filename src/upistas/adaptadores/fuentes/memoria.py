"""Fuentes en memoria: para tests y para arrancar antes de tener Excel y ERP conectados."""
from __future__ import annotations

from dataclasses import dataclass, field

from upistas.dominio.modelos import Asiento, Pedido, Proveedor


@dataclass
class MaestroEnMemoria:
    lista_proveedores: list[Proveedor] = field(default_factory=list)
    lista_pedidos: list[Pedido] = field(default_factory=list)

    def proveedores(self) -> list[Proveedor]:
        return self.lista_proveedores

    def pedidos(self) -> list[Pedido]:
        return self.lista_pedidos


@dataclass
class ErpEnMemoria:
    lista_asientos: list[Asiento] = field(default_factory=list)

    def asientos(self) -> list[Asiento]:
        return self.lista_asientos
