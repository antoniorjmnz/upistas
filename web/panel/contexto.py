"""Lo que todas las pantallas necesitan saber: el lote actual, cuánto hay por revisar y cómo está el ERP."""
from __future__ import annotations

from django.http import HttpRequest

from web.panel import consultas, sincronizacion
from web.panel.models import SincronizacionERP
from web.panel.views import chat


def _estado_erp() -> dict:
    ultima = SincronizacionERP.objects.first()
    if ultima is None:
        return {"clase": "sin", "texto": "ERP: todavía sin copia", "detalle": "Vaya a Conexión con el ERP y pulse Sincronizar ahora"}
    if ultima.ok:
        cuando = ultima.fin or ultima.inicio
        estado = {"clase": "bien", "texto": f"ERP al día · {cuando:%H:%M}", "detalle": f"Copia de las {cuando:%H:%M} del {cuando:%d/%m}, {ultima.n_asientos} asientos"}
        if sincronizacion.esta_activa():  # el punto late y se dice que la web trae sola el ERP
            estado["clase"], estado["sub"] = "bien viva", "sincronización constante"
        return estado
    copia = SincronizacionERP.objects.filter(ok=True).first()
    detalle = f"Seguimos con la copia de las {copia.fin:%H:%M}" if copia else "No hay ninguna copia con la que trabajar"
    return {"clase": "mal", "texto": "ERP sin respuesta", "detalle": detalle}


def panel(request: HttpRequest) -> dict:
    ejecucion = consultas.ultima_ejecucion()
    return {
        "lote_actual": ejecucion.lote if ejecucion else None,
        "pendientes_revision": consultas.pendientes_de_revision(ejecucion).count() if ejecucion else 0,
        "erp_estado": _estado_erp(),
        # El panel «Preguntar» está en todas las pantallas: la conversación abierta y la lista para cambiar de una a otra.
        "chat": chat.historial_de(request),
        "conversacion_actual": chat.conversacion_actual(request),
        "lista_abierta": bool(request.GET.get("lista")),  # «Ver todas» llega con ?lista=1 y la lista sale desplegada
        **chat.lista_de_conversaciones(),
    }
