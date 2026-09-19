"""Filtros pequeños para las plantillas: cómo se pinta un resultado, un importe, un campo leído."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template

from web.panel.consultas import CLASE, ETIQUETA

register = template.Library()


@register.filter
def pildora(resultado: str) -> str:
    """Clase CSS de la píldora: PAGAR → bien, NO_PAGAR → mal, ESCALAR → ojo."""
    return CLASE.get(resultado, "neutra")


@register.filter
def etiqueta(resultado: str) -> str:
    """Cómo se le llama a Alberto: Pagar, No pagar, Revisar."""
    return ETIQUETA.get(resultado, resultado)


@register.filter
def euros(valor) -> str:
    """1234.5 → '1.234,50 €'. Vacío si no hay valor."""
    if valor in (None, ""):
        return ""
    try:
        n = Decimal(str(valor))
    except InvalidOperation:
        return str(valor)
    entero, decimales = f"{n:,.2f}".split(".")
    return f"{entero.replace(',', '.')},{decimales} €"


@register.filter
def campo(extraida: dict | None, nombre: str):
    """El valor de un campo del contrato factura_extraida, o None."""
    if not extraida:
        return None
    return ((extraida.get("campos") or {}).get(nombre) or {}).get("valor")


@register.filter
def confianza(extraida: dict | None, nombre: str) -> float | None:
    if not extraida:
        return None
    return ((extraida.get("campos") or {}).get(nombre) or {}).get("confianza")


@register.filter
def clave(diccionario: dict | None, nombre: str):
    """Acceso a una clave con nombre dinámico: {{ resumen|clave:"PAGAR" }}."""
    return (diccionario or {}).get(nombre)
