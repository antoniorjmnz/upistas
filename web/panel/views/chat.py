"""Preguntar: Alberto escribe y la web contesta con los datos que tiene (#39, ver docs/asistente.md).

El mismo código sirve la pantalla entera (/preguntar/) y el panel lateral que hay en las demás
pantallas: la conversación vive en la sesión y cada respuesta llega como fragmento htmx.
"""
from __future__ import annotations

from django.core import signing
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve
from django.views.decorators.http import require_POST

from web.panel.models import Pregunta, Proveedor

MAX_MENSAJES = 20  # la sesión no es un archivo: se conserva lo último
MAX_PENDIENTES = 20  # propuestas sin confirmar ni descartar que se recuerdan


def historial_de(request: HttpRequest) -> list[dict]:
    return request.session.setdefault("chat", [])


def pendientes_de(request: HttpRequest) -> list[str]:
    """Los nonces de las propuestas que Alberto todavía puede confirmar."""
    return request.session.setdefault("propuestas_pendientes", [])


def _guardar(request: HttpRequest, historial: list[dict]) -> None:
    del historial[:-MAX_MENSAJES]
    pendientes = pendientes_de(request)
    del pendientes[:-MAX_PENDIENTES]
    request.session.modified = True


def _olvidar_propuesta(request: HttpRequest, historial: list[dict], nonce: str | None) -> None:
    """La propuesta deja de estar pendiente: ni en la sesión ni en las tarjetas de la conversación."""
    pendientes = pendientes_de(request)
    while nonce in pendientes:
        pendientes.remove(nonce)
    for m in historial:
        m["propuestas"] = [p for p in m.get("propuestas") or [] if p.get("nonce") != nonce]


def contexto_de(ruta: str | None) -> dict | None:
    """En qué pantalla está Alberto, a partir de la ruta que manda el panel. Solo rutas de esta web."""
    if not ruta or not ruta.startswith("/") or ruta.startswith("//"):
        return None
    try:
        coincidencia = resolve(ruta.split("?")[0])
    except Resolver404:
        return None
    if coincidencia.namespace != "panel":
        return None
    contexto = {"ruta": ruta[:300], "pantalla": coincidencia.url_name}
    contexto.update({k: str(v) for k, v in coincidencia.kwargs.items()})
    if coincidencia.url_name in ("proveedor", "proveedor_editar"):
        p = Proveedor.objects.filter(pk=coincidencia.kwargs.get("id")).first()
        contexto["proveedor"] = f"{p.nombre} ({p.codigo})" if p else f"nº {coincidencia.kwargs.get('id')}"
    return contexto


def preguntar(request: HttpRequest) -> HttpResponse:
    """El chat de Alberto: cada pregunta va al asistente y la conversación vive en la sesión."""
    from web.panel.asistente import helmcode
    from web.panel.asistente.agente import responder

    historial = historial_de(request)
    if request.method == "POST":
        texto = (request.POST.get("pregunta") or "").strip()
        if not texto:
            return redirect("panel:preguntar")
        contexto = contexto_de(request.POST.get("ruta"))
        salida = responder(texto, historial, helmcode.completar, contexto)
        Pregunta.objects.create(
            texto=texto, respuesta=salida.texto, ok=salida.ok, error=salida.error,
            tokens_in=salida.tokens_in, tokens_out=salida.tokens_out, segundos=salida.segundos,
        )
        historial.append({"quien": "alberto", "texto": texto})
        historial.append({
            "quien": "asistente", "texto": salida.texto, "fuentes": salida.fuentes,
            "enlaces": salida.enlaces, "propuestas": salida.propuestas,
        })
        pendientes_de(request).extend(p["nonce"] for p in salida.propuestas if p.get("nonce"))
        _guardar(request, historial)
        if request.headers.get("HX-Request"):
            return render(request, "panel/_mensajes.html", {"mensajes": historial[-1:]})
    return render(request, "panel/preguntar.html", {"historial": historial, "pagina_actual": "preguntar"})


@require_POST
def accion(request: HttpRequest) -> HttpResponse:
    """Alberto ha pulsado «Confirmar» o «No» en una propuesta del asistente.

    Confirmar: el token firmado lleva el tipo, los datos y el nonce; caducado, manipulado, de un tipo
    fuera de la lista, ya hecho o que no esté pendiente en la sesión, no se hace nada y se le dice. Si vale,
    se hace y queda registrado; la propuesta desaparece de la conversación y en su lugar queda «Hecho: …».
    No (`rechazar=1`): la propuesta se olvida sin hacer nada.
    """
    from web.panel.asistente import acciones

    token = request.POST.get("token") or ""
    historial = historial_de(request)
    if request.POST.get("rechazar"):
        _olvidar_propuesta(request, historial, acciones.nonce_de(token))
        mensaje = {"quien": "asistente", "aviso": "Vale, no se hace nada."}
    else:
        mensaje = _confirmar(request, historial, token)
    historial.append(mensaje)
    _guardar(request, historial)
    if request.headers.get("HX-Request"):
        return render(request, "panel/_mensajes.html", {"mensajes": [mensaje]})
    return redirect("panel:preguntar")


def _confirmar(request: HttpRequest, historial: list[dict], token: str) -> dict:
    from web.panel.asistente import acciones

    try:
        tipo, datos, nonce = acciones.leer_token(token)
    except signing.SignatureExpired:
        _olvidar_propuesta(request, historial, acciones.nonce_de(token))
        return {"quien": "asistente", "aviso": "Esa propuesta ha caducado (valen diez minutos). Vuelva a pedírmelo."}
    except signing.BadSignature:
        return {"quien": "asistente", "aviso": "Esa propuesta no es válida. Vuelva a pedírmelo."}
    if nonce not in pendientes_de(request) or acciones.ya_hecha(nonce):
        _olvidar_propuesta(request, historial, nonce)
        return {"quien": "asistente", "aviso": "Esa propuesta ya se hizo o se descartó. Si la quiere otra vez, vuelva a pedírmelo."}
    _olvidar_propuesta(request, historial, nonce)  # antes de hacerla: aunque falle, no se reintenta sola
    hecha = acciones.ejecutar(tipo, datos, nonce)
    return {"quien": "asistente", "hecho": hecha.resultado, "ok": hecha.ok, "enlaces": [e for e in [acciones.enlace(hecha)] if e]}
