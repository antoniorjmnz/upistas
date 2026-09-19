"""Lo que todas las pantallas necesitan saber: el lote actual, cuánto hay por revisar y cómo está el ERP."""
from __future__ import annotations

from django.http import HttpRequest

from web.panel import consultas
from web.panel.models import SincronizacionERP


def _estado_erp() -> dict:
    ultima = SincronizacionERP.objects.first()
    if ultima is None:
        return {"clase": "sin", "texto": "ERP: todavía sin copia", "detalle": "Vaya a Conexión con el ERP y pulse Sincronizar ahora"}
    if ultima.ok:
        cuando = ultima.fin or ultima.inicio
        return {"clase": "bien", "texto": f"ERP al día · {cuando:%H:%M}", "detalle": f"Copia de las {cuando:%H:%M} del {cuando:%d/%m}, {ultima.n_asientos} asientos"}
    copia = SincronizacionERP.objects.filter(ok=True).first()
    detalle = f"Seguimos con la copia de las {copia.fin:%H:%M}" if copia else "No hay ninguna copia con la que trabajar"
    return {"clase": "mal", "texto": "ERP sin respuesta", "detalle": detalle}


def panel(request: HttpRequest) -> dict:
    ejecucion = consultas.ultima_ejecucion()
    return {
        "lote_actual": ejecucion.lote if ejecucion else None,
        "pendientes_revision": consultas.pendientes_de_revision(ejecucion).count() if ejecucion else 0,
        "erp_estado": _estado_erp(),
        # El panel «Preguntar» está en todas las pantallas y enseña la conversación que va en la sesión.
        "chat": request.session.get("chat", []) if hasattr(request, "session") else [],
    }
