"""El ERP con el que decide el pipeline: la copia local, no el bridge en vivo."""
from __future__ import annotations

from upistas.dominio.modelos import Asiento
from upistas.puertos import AlmacenERP


class ErpDesdeCopia:
    def __init__(self, almacen: AlmacenERP, version: str | None = None) -> None:
        self.almacen = almacen
        self.version = version

    def asientos(self) -> list[Asiento]:
        return self.almacen.asientos(self.version)
