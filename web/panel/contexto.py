"""Lo que todas las pantallas necesitan saber: qué lote es el actual y cuánto hay por revisar."""
from __future__ import annotations

from django.http import HttpRequest

from web.panel import consultas


def panel(request: HttpRequest) -> dict:
    ejecucion = consultas.ultima_ejecucion()
    return {
        "lote_actual": ejecucion.lote if ejecucion else None,
        "pendientes_revision": consultas.pendientes_de_revision(ejecucion).count() if ejecucion else 0,
    }
