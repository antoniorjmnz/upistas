"""Puertos: lo que la aplicación necesita del mundo exterior, sin decir cómo se consigue.

Cada puerto tiene una o varias implementaciones en `adaptadores/`. Para soportar algo nuevo
(emails, otro ERP, otro proveedor de LLM) se añade un adaptador; el dominio y la aplicación
no cambian.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.modelos import Asiento, Pedido, Proveedor


class LecturaFallida(Exception):
    """El lector no pudo sacar la factura de este documento. El siguiente lector lo intentará."""


class LectorDocumento(Protocol):
    """Convierte un documento (PDF, escaneo, email...) en una factura extraída."""

    nombre: str

    def acepta(self, ruta: Path) -> bool: ...

    def leer(self, ruta: Path) -> FacturaExtraida: ...


class FuenteMaestro(Protocol):
    """Datos de proveedores y pedidos (hoy: el Excel de Alberto)."""

    def proveedores(self) -> list[Proveedor]: ...

    def pedidos(self) -> list[Pedido]: ...


class FuenteERP(Protocol):
    """Asientos contables oficiales (hoy: el bridge HTTP de 2009)."""

    def asientos(self) -> list[Asiento]: ...


class ModeloLenguaje(Protocol):
    """Un LLM que devuelve JSON conforme a un esquema. Solo extrae; nunca decide pagos."""

    nombre: str

    def extraer_json(self, instrucciones: str, texto: str | None = None, imagenes: list[bytes] | None = None) -> dict: ...
