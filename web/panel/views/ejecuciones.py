"""Cada pasada por un lote: cifras, con qué datos se decidió, qué cambió y el outcomes.jsonl."""
from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from web.panel import consultas
from web.panel.models import Decision, Ejecucion

# Cómo se leyó cada factura, dicho para Alberto.
METODOS = {
    "texto_determinista": "leídas del texto del PDF, sin inteligencia artificial",
    "texto_llm": "leídas con ayuda de la inteligencia artificial",
    "vision_llm": "escaneadas, leídas por la inteligencia artificial mirando la imagen",
    "ninguno": "no se pudieron leer",
}

# Lo que hay en Ejecucion.hardware, con nombres que se entienden.
HARDWARE = {"sistema": "Sistema", "maquina": "Procesador", "nucleos": "Núcleos", "python": "Python"}


def nombre_lote(lote: str) -> str:
    """"lote1" → "Lote 1". Cualquier otro nombre se deja como está."""
    return f"Lote {lote[4:]}" if lote.startswith("lote") and lote[4:].isdigit() else lote


def cifras(ejecucion: Ejecucion) -> dict:
    """Las cifras de una pasada ya masticadas: cuántas de cada, cuánto tardó y cuánto costó."""
    r = ejecucion.resumen or {}
    documentos = r.get("documentos") or 0
    segundos = r.get("segundos")
    if not segundos and ejecucion.fin:
        segundos = (ejecucion.fin - ejecucion.inicio).total_seconds()
    por_metodo = r.get("por_metodo") or {}
    return {
        "documentos": documentos,
        "PAGAR": r.get("PAGAR") or 0,
        "NO_PAGAR": r.get("NO_PAGAR") or 0,
        "ESCALAR": r.get("ESCALAR") or 0,
        "leidos": r.get("leidos") or 0,
        "segundos": segundos,
        "por_segundo": round(documentos / segundos, 1) if segundos and documentos else None,
        "tokens_in": r.get("tokens_in") or 0,
        "tokens_out": r.get("tokens_out") or 0,
        "coste_eur": r.get("coste_eur") or 0,
        "sin_ia": por_metodo.get("texto_determinista") or 0,
        "metodos": [{"texto": METODOS.get(m, m), "n": n} for m, n in sorted(por_metodo.items(), key=lambda kv: -kv[1])],
    }


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
