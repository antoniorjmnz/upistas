from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Resultado(StrEnum):
    PAGAR = "PAGAR"
    NO_PAGAR = "NO_PAGAR"
    ESCALAR = "ESCALAR"


# Cuando varias reglas fallan gana la más restrictiva.
GRAVEDAD = {Resultado.PAGAR: 0, Resultado.ESCALAR: 1, Resultado.NO_PAGAR: 2}


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    nif: str
    iban: str


@dataclass(frozen=True)
class Pedido:
    id: str
    proveedor_id: str
    nif: str
    importe: Decimal


@dataclass(frozen=True)
class Asiento:
    """Un asiento del ERP: la referencia contable oficial."""

    id: str
    pedido: str
    proveedor_id: str
    nif: str
    importe: Decimal
    fecha: date
    estado: str  # PENDIENTE | PAGADA


@dataclass(frozen=True)
class Factura:
    """Lo que se leyó de un documento. Un campo a None significa que no se pudo leer."""

    file_id: str
    nif: str | None = None
    iban: str | None = None
    pedido: str | None = None
    fecha: date | None = None
    base: Decimal | None = None
    iva_pct: Decimal | None = None
    iva: Decimal | None = None
    total: Decimal | None = None
    lineas: tuple[Decimal, ...] = ()


@dataclass(frozen=True)
class Referencias:
    """Todo lo que las reglas pueden consultar además de la factura."""

    proveedores: dict[str, Proveedor]  # por NIF
    pedidos: dict[str, Pedido]  # Excel, por id de pedido
    asientos: dict[str, Asiento]  # ERP, por id de pedido
    hoy: date
    pedidos_ya_decididos: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Comprobacion:
    regla: str
    ok: bool
    detalle: str = ""


@dataclass(frozen=True)
class Decision:
    file_id: str
    resultado: Resultado
    motivo: str
    norma: str
    comprobaciones: tuple[Comprobacion, ...] = field(default_factory=tuple)
    pedido: str | None = None
