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


@register.filter
def regla(id_regla: str) -> str:
    """El nombre de una regla en palabras de Alberto: {{ r.id|regla }}."""
    from web.panel.consultas import nombre_regla

    return nombre_regla(id_regla)


@register.filter
def lote(nombre: str) -> str:
    """"lote1" → "Lote 1"."""
    from web.panel.consultas import nombre_lote

    return nombre_lote(nombre)


_ICONOS = {
    "marca": '<rect x="3" y="3" width="18" height="18" rx="5" fill="currentColor" stroke="none"/><path d="M7.5 12.5l3 3 6-6.5" stroke="#fff"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "ojo": '<path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "doc": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
    "buscar": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "flecha": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "alerta": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
    "reloj": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}


@register.simple_tag
def icono(nombre: str, tamano: int = 18) -> str:
    """Un icono en línea (SVG, sin ficheros ni red): {% icono "check" 18 %}."""
    from django.utils.safestring import mark_safe

    cuerpo = _ICONOS.get(nombre)
    if cuerpo is None:
        return ""
    return mark_safe(
        f'<svg width="{int(tamano)}" height="{int(tamano)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{cuerpo}</svg>'
    )
