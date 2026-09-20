from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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


def _antiguedad(a: Asiento) -> tuple[date, str]:
    return (a.fecha or date.min, a.id)


def asientos_por_pedido(asientos: Iterable[Asiento]) -> dict[str, tuple[Asiento, ...]]:
    """Los apuntes del ERP agrupados por pedido, del más antiguo al más reciente. Puede haber varios."""
    grupos: dict[str, list[Asiento]] = defaultdict(list)
    for a in sorted(asientos, key=_antiguedad):
        grupos[a.pedido].append(a)
    return {pedido: tuple(apuntes) for pedido, apuntes in grupos.items()}


def apuntes_contradictorios(apuntes: Sequence[Asiento]) -> bool:
    """El ERP tiene varios apuntes de un pedido que no cuadran entre sí (proveedor, NIF o importe distintos).

    Si alguno está pagado no se considera contradicción: ese manda y el pedido no se vuelve a pagar.
    """
    if any(a.estado == "PAGADA" for a in apuntes):
        return False
    return len({(a.proveedor_id, a.nif, a.importe) for a in apuntes}) > 1


def asiento_que_manda(apuntes: Sequence[Asiento]) -> Asiento | None:
    """Con qué apunte del ERP se decide un pedido que tiene varios.

    Si alguno está PAGADA, el pagado más reciente: nunca se paga dos veces. Si todos cuadran entre sí,
    el más reciente. Si no cuadran, ninguno: el ERP se contradice y lo mira una persona.
    """
    if not apuntes:
        return None
    pagados = [a for a in apuntes if a.estado == "PAGADA"]
    if pagados:
        return max(pagados, key=_antiguedad)
    if apuntes_contradictorios(apuntes):
        return None
    return max(apuntes, key=_antiguedad)


@dataclass(frozen=True)
class Nota:
    """Texto del documento que no es un dato: condiciones, avisos, instrucciones. Nunca se obedece."""

    texto: str
    categorias: tuple[str, ...] = ()

    def es(self, categoria: str) -> bool:
        return categoria in self.categorias


@dataclass(frozen=True)
class EvaluacionNotas:
    requiere_revision: bool
    motivo: str
    evidencia: str = ""
    modelo: str = ""
    version_prompt: str = ""
    error: str = ""
    desde_cache: bool = False
    tokens_in: int = 0
    tokens_out: int = 0


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
    divisa: str = "EUR"  # moneda de base, iva y total (código ISO); sin marca en el documento, euros
    por_ocr: bool = False  # leída por OCR o visión: un dato que no cuadra no prueba un incumplimiento (ver Norma.evaluar)
    lineas: tuple[Decimal, ...] = ()
    numero: str | None = None
    proveedor_nombre: str | None = None
    cliente_cif: str | None = None
    notas: tuple[Nota, ...] = ()
    alertas: tuple[str, ...] = ()  # del fichero: estructura reparada, JavaScript, caracteres invisibles...
    tipo_documento: str = "texto"  # texto | escaneado | blanco | roto | cifrado | otro
    metodo: str = "texto_determinista"  # texto_determinista | ocr_determinista | texto_llm | vision_llm | ninguno
    ausentes: frozenset[str] = frozenset()
    no_leidos: frozenset[str] = frozenset()
    sha256: str = ""
    errores_lectura: tuple[str, ...] = ()
    evaluacion_notas: EvaluacionNotas | None = None
    fecha_texto: str | None = None  # la fecha tal como está escrita cuando no es una fecha real (31/02/2026)

    def dudoso(self, campo: str) -> bool:
        return campo in self.no_leidos


# Cada campo leído, como se nombra dentro de un motivo («no se pudo leer la fecha»).
NOMBRE_CAMPO = {
    "nif": "el NIF", "iban": "el IBAN", "pedido": "el número de pedido", "numero_factura": "el número de factura",
    "fecha": "la fecha", "base": "la base imponible", "iva_pct": "el porcentaje de IVA", "iva": "el IVA", "total": "el total",
}


def enumerar(textos: Sequence[str]) -> str:
    """«a», «a y b», «a, b y c»."""
    if len(textos) < 2:
        return "".join(textos)
    return ", ".join(textos[:-1]) + " y " + textos[-1]


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
    asientos: Mapping[str, tuple[Asiento, ...]]  # ERP (copia local), por id de pedido; puede haber varios apuntes
    hoy: date
    pedidos_ya_decididos: frozenset[str] = frozenset()  # aprobados para pago en lotes anteriores
    marcados_por_alberto: frozenset[str] = frozenset()  # hoja pendiente_revisar del Excel
    facturas_del_lote: Mapping[str, tuple[FacturaResumen, ...]] = field(default_factory=dict)  # por pedido
    version_datos: str = ""  # con qué copia del ERP y del Excel se decidió
    proveedores_por_id: dict[str, Proveedor] = field(default_factory=dict)
    hashes_ya_aprobados: frozenset[str] = frozenset()

    def asiento(self, pedido: str | None) -> Asiento | None:
        """El apunte del ERP que manda para ese pedido; None si no hay ninguno o si el ERP se contradice."""
        return asiento_que_manda(self.asientos.get(pedido, ())) if pedido else None

    def erp_contradictorio(self, pedido: str | None) -> bool:
        return bool(pedido) and apuntes_contradictorios(self.asientos.get(pedido, ()))


@dataclass(frozen=True)
class Comprobacion:
    regla: str
    ok: bool
    detalle: str = ""  # la traza completa: es lo que va en reglas[] del outcome
    motivo: str = ""  # cómo se cuenta en el motivo de la decisión, si no es tal cual el detalle


@dataclass(frozen=True)
class Decision:
    file_id: str
    resultado: Resultado
    motivo: str
    norma: str
    comprobaciones: tuple[Comprobacion, ...] = field(default_factory=tuple)
    pedido: str | None = None
    alertas: tuple[str, ...] = ()  # lo que Alberto debe ver aunque la decisión sea clara
