"""Puertos: lo que la aplicación necesita del mundo exterior, sin decir cómo se consigue.

Cada puerto tiene una o varias implementaciones en `adaptadores/`. Para soportar algo nuevo
(emails, otro ERP, otro proveedor de LLM) se añade un adaptador; el dominio y la aplicación
no cambian.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    """Asientos contables oficiales con los que decidir (hoy: la copia local del ERP)."""

    def asientos(self) -> list[Asiento]: ...


# --- ERP remoto y su copia local -------------------------------------------------------------


class ErrorERP(Exception):
    """El ERP no respondió bien ni después de reintentar."""


@dataclass(frozen=True)
class EstadisticasDescarga:
    peticiones: int = 0
    reintentos_ora: int = 0  # ORA-00600: error interno, se reintenta la misma consulta
    esperas_429: int = 0  # ERP-429: demasiadas peticiones, se espera Retry-After
    relogins: int = 0  # SES-401: sesión caducada, se vuelve a identificar
    errores_red: int = 0
    segundos: float = 0.0


@dataclass(frozen=True)
class DescargaERP:
    asientos: tuple[Asiento, ...]
    lote2_cargado: bool
    estadisticas: EstadisticasDescarga


class ClienteERP(Protocol):
    """El ERP de Alberto. Solo se lee: no tiene forma de escribir."""

    def descargar(self) -> DescargaERP: ...


@dataclass(frozen=True)
class Sincronizacion:
    """Una descarga del ERP, haya ido bien o mal. Es el historial que ve Alberto."""

    inicio: datetime
    fin: datetime
    ok: bool
    version: str | None = None
    n_asientos: int = 0
    lote2_cargado: bool = False
    estadisticas: EstadisticasDescarga = field(default_factory=EstadisticasDescarga)
    error: str | None = None
    nuevos: int = 0  # respecto a la versión anterior
    modificados: int = 0
    eliminados: int = 0


class AlmacenERP(Protocol):
    """Copia local y versionada de los asientos, y el historial de sincronizaciones."""

    def registrar(self, sincronizacion: Sincronizacion, asientos: tuple[Asiento, ...] | None) -> None:
        """Guarda la sincronización y, si es una versión nueva, sus asientos."""
        ...

    def asientos(self, version: str | None = None) -> list[Asiento]:
        """Asientos de una versión; sin versión, los de la última descarga correcta."""
        ...

    def ultima(self, solo_correctas: bool = True) -> Sincronizacion | None: ...


class ModeloLenguaje(Protocol):
    """Un LLM que devuelve JSON conforme a un esquema. Solo extrae; nunca decide pagos."""

    nombre: str

    def extraer_json(self, instrucciones: str, texto: str | None = None, imagenes: list[bytes] | None = None) -> dict: ...
