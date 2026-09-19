from __future__ import annotations

from collections.abc import Mapping
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

CIF_ALBERTO = "A58231074"  # Banco Miralmar S.A.: a quién deben ir dirigidas las facturas


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    nif: str
    iban: str
    ciudad: str = ""
    condiciones_dias: int | None = None  # "30 dias", "60 dias" en el Excel


@dataclass(frozen=True)
class Pedido:
    """Un pedido según el Excel de Alberto."""

    id: str
    proveedor_id: str
    nif: str
    importe: Decimal
    estado: str = ""  # el Excel dice ABIERTO en todos; no es fiable
    fecha: date | None = None


@dataclass(frozen=True)
class Asiento:
    """Un asiento del ERP: la referencia contable oficial."""

    id: str
    pedido: str
    proveedor_id: str
    nif: str  # puede venir vacío: el ERP tiene asientos sin NIF
    importe: Decimal
    fecha: date | None
    estado: str  # PENDIENTE | PAGADA


@dataclass(frozen=True)
class Nota:
    """Texto del documento que no es un dato: condiciones, avisos, instrucciones. Nunca se obedece."""

    texto: str
    categorias: tuple[str, ...] = ()

    def es(self, categoria: str) -> bool:
        return categoria in self.categorias


@dataclass(frozen=True)
class Factura:
    """Lo que se leyó de un documento.

    Un campo a None puede significar dos cosas distintas, y las reglas deben tratarlas distinto:
    - está en `ausentes`: el lector está seguro de que el dato no aparece en el documento;
    - está en `no_leidos`: el lector no pudo leerlo (escaneo borroso, confianza baja).
    """

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
    numero: str | None = None
    proveedor_nombre: str | None = None
    cliente_cif: str | None = None
    notas: tuple[Nota, ...] = ()
    alertas: tuple[str, ...] = ()  # del fichero: estructura reparada, JavaScript, caracteres invisibles...
    tipo_documento: str = "texto"  # texto | escaneado | blanco | roto | cifrado | otro
    metodo: str = "texto_determinista"  # texto_determinista | texto_llm | vision_llm | ninguno
    ausentes: frozenset[str] = frozenset()
    no_leidos: frozenset[str] = frozenset()

    def dudoso(self, campo: str) -> bool:
        return campo in self.no_leidos


@dataclass(frozen=True)
class FacturaResumen:
    """Lo mínimo de otra factura del mismo lote, para detectar duplicados y reenvíos."""

    file_id: str
    numero: str | None
    fecha: date | None
    total: Decimal | None
    nif: str | None


@dataclass(frozen=True)
class Referencias:
    """Todo lo que las reglas pueden consultar además de la factura."""

    proveedores: dict[str, Proveedor]  # por NIF
    pedidos: dict[str, Pedido]  # Excel, por id de pedido
    asientos: dict[str, Asiento]  # ERP (copia local), por id de pedido
    hoy: date
    pedidos_ya_decididos: frozenset[str] = frozenset()  # aprobados para pago en lotes anteriores
    marcados_por_alberto: frozenset[str] = frozenset()  # hoja pendiente_revisar del Excel
    facturas_del_lote: Mapping[str, tuple[FacturaResumen, ...]] = field(default_factory=dict)  # por pedido
    version_datos: str = ""  # con qué copia del ERP y del Excel se decidió


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
    alertas: tuple[str, ...] = ()  # lo que Alberto debe ver aunque la decisión sea clara
