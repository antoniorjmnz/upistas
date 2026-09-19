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
    "casa": '<path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "archivo": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    "erp": '<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>',
    "lista": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
    "externo": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    "subir": '<path d="M12 16V4M6 10l6-6 6 6"/><path d="M4 20h16"/>',
    "proveedores": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M17 3.5a4 4 0 0 1 0 9M22 21a7 7 0 0 0-5-6.7"/>',
    "mas": '<path d="M12 5v14M5 12h14"/>',
    "editar": '<path d="M4 20h4l11-11-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "papelera": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "filtro": '<path d="M3 5h18l-7 8.5V19l-4 2v-7.5z"/>',
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


@register.filter
def iniciales(nombre: str | None) -> str:
    """'Construcciones Benimaclet S.A.' → 'CB'. Sin nombre, un interrogante."""
    if not nombre:
        return "?"
    palabras = [p for p in str(nombre).replace(".", " ").split() if p.upper() not in {"S", "SA", "SL", "SLU", "SCOOP", "DE", "DEL", "LA", "EL", "Y", "AND"}]
    letras = "".join(p[0] for p in palabras[:2]).upper()
    return letras or str(nombre)[:2].upper()


@register.filter
def color_avatar(nombre: str | None) -> str:
    """Una de seis clases de color (a-f), siempre la misma para el mismo proveedor."""
    if not nombre:
        return "f"
    return "abcdef"[sum(ord(c) for c in str(nombre)) % 6]


@register.simple_tag
def estatico(ruta: str) -> str:
    """Como {% static %}, pero con la fecha del fichero detrás para que el navegador no use una copia vieja."""
    import os

    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    fichero = finders.find(ruta)
    version = int(os.path.getmtime(fichero)) if fichero else 0
    return f"{static(ruta)}?v={version}"


@register.filter
def fecha_corta(texto: str | None) -> str:
    """'2026-01-08' → '8/1/2026'. Lo que no sea una fecha se deja tal cual."""
    from datetime import date

    try:
        d = date.fromisoformat(str(texto).strip())
    except (ValueError, AttributeError):
        return str(texto or "")
    return f"{d.day}/{d.month}/{d.year}"
