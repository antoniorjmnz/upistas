"""Cada pasada por un lote: cifras, con qué datos se decidió, qué cambió y el outcomes.jsonl."""
from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from web.panel import consultas
from web.panel.consultas import cifras, nombre_lote
from web.panel.models import Decision, Ejecucion

# Lo que hay en Ejecucion.hardware, con nombres que se entienden.
HARDWARE = {"sistema": "Sistema", "maquina": "Procesador", "nucleos": "Núcleos", "python": "Python"}


def lista(request: HttpRequest) -> HttpResponse:
    filas = [{"e": e, "c": cifras(e), "lote": nombre_lote(e.lote)} for e in Ejecucion.objects.all()]
    return render(request, "panel/ejecuciones.html", {"filas": filas})


def detalle(request: HttpRequest, id: int) -> HttpResponse:
    ejecucion = get_object_or_404(Ejecucion, pk=id)
    anterior, cambios = consultas.cambios_respecto_a_la_anterior(ejecucion)
    return render(request, "panel/ejecucion.html", {
        "ejecucion": ejecucion,
        "nombre_lote": nombre_lote(ejecucion.lote),
        "cifras": cifras(ejecucion),
        "anterior": anterior,
        "cambios": cambios,
        "hardware": [{"que": HARDWARE.get(k, k), "valor": v} for k, v in (ejecucion.hardware or {}).items()],
    })


def outcomes(request: HttpRequest, id: int) -> HttpResponse:
    """El fichero que se entrega: una línea JSON por factura, tal cual se decidió."""
    ejecucion = get_object_or_404(Ejecucion, pk=id)
    lineas = Decision.objects.filter(ejecucion=ejecucion).order_by("documento__file_id").values_list("outcome", flat=True)
    cuerpo = "".join(json.dumps(outcome, ensure_ascii=False) + "\n" for outcome in lineas)
    nombre = "outcomes.jsonl" if ejecucion.lote == "lote1" else f"outcomes_{ejecucion.lote}.jsonl"
    respuesta = HttpResponse(cuerpo, content_type="application/x-ndjson; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta
