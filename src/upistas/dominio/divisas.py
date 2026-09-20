"""Importes en otra moneda: el pedido va en euros y la factura no siempre.

Los tipos de referencia viven en `normas/divisas.toml` (unidades de divisa por 1 €), no en el código.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENTIMOS = Decimal("0.01")


@dataclass(frozen=True)
class TiposDeCambio:
    tipos: Mapping[str, Decimal] = field(default_factory=dict)  # «USD» → 1.0870 (USD por 1 €)
    tolerancia_pct: Decimal = Decimal("0.5")  # diferencia admitida con el pedido, en % del pedido

    @classmethod
    def desde_datos(cls, datos: Mapping) -> TiposDeCambio:
        """Lo que trae `divisas.toml`: `[tipos]` y `tolerancia_pct`."""
        tipos = {codigo.upper(): Decimal(str(tipo)) for codigo, tipo in (datos.get("tipos") or {}).items()}
        return cls(tipos, Decimal(str(datos.get("tolerancia_pct", "0.5"))))


def al_cambio(importe: Decimal | None, divisa: str, tipos: Mapping[str, Decimal]) -> Decimal | None:
    """2.450,00 USD a 1,0870 USD por euro → 2.253,91 €. None si no hay importe o no hay tipo para esa divisa."""
    tipo = tipos.get(divisa)
    if importe is None or not tipo:
        return None
    return (Decimal(importe) / Decimal(tipo)).quantize(CENTIMOS, rounding=ROUND_HALF_UP)


def cuadra_al_cambio(en_euros: Decimal, pedido: Decimal, tolerancia_pct: Decimal) -> bool:
    """El importe pasado a euros coincide con el pedido salvo el redondeo del tipo (tolerancia en % del pedido)."""
    return abs(en_euros - pedido) <= abs(pedido) * tolerancia_pct / 100


def importe_es(valor: Decimal, divisa: str = "EUR") -> str:
    """2450 → «2.450,00 USD»; en euros, «2.254,00 €»."""
    entero, decimales = f"{Decimal(valor):,.2f}".split(".")
    return f"{entero.replace(',', '.')},{decimales} {'€' if divisa == 'EUR' else divisa}"


def tipo_es(tipo: Decimal) -> str:
    """1.087 → «1,0870»: el tipo con cuatro decimales, como se escribe aquí."""
    return f"{Decimal(tipo):.4f}".replace(".", ",")
