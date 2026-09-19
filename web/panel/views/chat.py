"""Preguntar: Alberto escribe y la web contesta con los datos que tiene (#39, ver docs/asistente.md)."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from web.panel.models import Pregunta


def preguntar(request: HttpRequest) -> HttpResponse:
    """El chat de Alberto: cada pregunta va al asistente y la conversación vive en la sesión."""
    from web.panel.asistente import helmcode
    from web.panel.asistente.agente import responder

    historial = request.session.setdefault("chat", [])
    if request.method == "POST":
        texto = (request.POST.get("pregunta") or "").strip()
        if not texto:
            return redirect("panel:preguntar")
        salida = responder(texto, historial, helmcode.completar)
        Pregunta.objects.create(
            texto=texto, respuesta=salida.texto, ok=salida.ok, error=salida.error,
            tokens_in=salida.tokens_in, tokens_out=salida.tokens_out, segundos=salida.segundos,
        )
        historial.append({"quien": "alberto", "texto": texto})
        historial.append({"quien": "asistente", "texto": salida.texto, "fuentes": salida.fuentes})
        del historial[:-40]  # la sesión no es un archivo: se conserva lo último
        request.session.modified = True
        if request.headers.get("HX-Request"):
            return render(request, "panel/_mensajes.html", {"mensajes": historial[-1:]})
    return render(request, "panel/preguntar.html", {"historial": historial, "pagina_actual": "preguntar"})
