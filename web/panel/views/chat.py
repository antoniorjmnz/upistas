"""Preguntar: Alberto escribe y la web contesta con los datos que tiene (#39, ver docs/asistente.md).

El mismo código sirve la pantalla entera (/preguntar/) y el panel lateral que hay en las demás
pantallas. Cada conversación vive en la base de datos (`Conversacion`, sus `Pregunta` y las
`AccionAsistente` que se confirmaron en ella); la sesión solo recuerda cuál está abierta, así que
la conversación sigue ahí al cambiar de pantalla y se puede volver a una de otro día.
"""
from __future__ import annotations

import textwrap

from django.core import signing
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from web.panel.models import AccionAsistente, Conversacion, Documento, Pregunta, Proveedor

MAX_PENDIENTES = 20  # propuestas sin confirmar ni descartar que se recuerdan
MAX_LISTA = 50       # conversaciones que enseña la lista del panel
EN_LA_BARRA = 3      # las últimas que salen en el menú lateral


def conversacion_actual(request: HttpRequest) -> Conversacion | None:
    """La conversación abierta en esta sesión, o ninguna (nueva, o se borró)."""
    if not hasattr(request, "session"):
        return None
    id_ = request.session.get("conversacion")
    if not id_:
        return None
    conversacion = Conversacion.objects.filter(pk=id_).first()
    if conversacion is None:
        request.session.pop("conversacion", None)
    return conversacion


def abrir_conversacion(request: HttpRequest, conversacion: Conversacion | None) -> None:
    if conversacion is None:
        request.session.pop("conversacion", None)
    else:
        request.session["conversacion"] = conversacion.pk
    request.session.modified = True


def historial_de(request: HttpRequest) -> list[dict]:
    """Los mensajes de la conversación abierta, reconstruidos desde la base de datos.

    Cada pregunta son dos mensajes (Alberto y el asistente); cada acción confirmada, uno «Hecho: …».
    Van en el orden en que ocurrieron.
    """
    return mensajes_de(conversacion_actual(request))


def mensajes_de(conversacion: Conversacion | None) -> list[dict]:
    from web.panel.asistente import acciones

    if conversacion is None:
        return []
    # Orden: por instante; a igual instante (pasa en el mismo milisegundo), por fila; y la pregunta antes que su respuesta.
    filas: list[tuple] = []
    for p in conversacion.preguntas.all():
        filas.append(((p.cuando, 0, p.pk, 0), {"quien": "alberto", "texto": p.texto}))
        detalles = p.detalles or {}
        filas.append(((p.cuando, 0, p.pk, 1), {
            "quien": "asistente", "texto": p.respuesta, "fuentes": detalles.get("fuentes") or [],
            "enlaces": detalles.get("enlaces") or [], "propuestas": detalles.get("propuestas") or [],
        }))
    for a in conversacion.acciones.all():
        filas.append(((a.cuando, 1, a.pk, 0), _mensaje_hecho(a, acciones.enlace(a))))
    filas.sort(key=lambda f: f[0])
    return [f[1] for f in filas]


def _mensaje_hecho(accion: AccionAsistente, enlace: dict | None) -> dict:
    return {"quien": "asistente", "hecho": accion.resultado, "ok": accion.ok, "enlaces": [e for e in [enlace] if e]}


def lista_de_conversaciones() -> dict:
    """Lo que el panel y el menú enseñan: todas (hasta un tope) y las tres últimas."""
    todas = list(Conversacion.objects.all()[:MAX_LISTA])
    return {
        "conversaciones": todas,
        "conversaciones_recientes": todas[:EN_LA_BARRA],
        "hay_mas_conversaciones": len(todas) > EN_LA_BARRA,
    }


def pendientes_de(request: HttpRequest) -> list[str]:
    """Los nonces de las propuestas que Alberto todavía puede confirmar."""
    return request.session.setdefault("propuestas_pendientes", [])


def _guardar(request: HttpRequest) -> None:
    pendientes = pendientes_de(request)
    del pendientes[:-MAX_PENDIENTES]
    request.session.modified = True


def _olvidar_propuesta(request: HttpRequest, nonce: str | None) -> None:
    """La propuesta deja de estar pendiente: ni en la sesión ni en las tarjetas de la conversación."""
    pendientes = pendientes_de(request)
    while nonce in pendientes:
        pendientes.remove(nonce)
    conversacion = conversacion_actual(request)
    if not nonce or conversacion is None:
        return
    for p in conversacion.preguntas.all():
        antes = (p.detalles or {}).get("propuestas") or []
        despues = [x for x in antes if x.get("nonce") != nonce]
        if len(despues) != len(antes):
            p.detalles = {**p.detalles, "propuestas": despues}
            p.save(update_fields=["detalles"])


def contexto_de(ruta: str | None) -> dict | None:
    """En qué pantalla está Alberto, a partir de la ruta que manda el panel. Solo rutas de esta web.

    Al modelo le llega la pantalla resuelta y sus identificadores comprobados contra la base de datos
    (lote y file_id de una factura que existe, nombre y código de un proveedor del maestro): nunca la
    ruta tal cual ni lo que lleve detrás del «?», que lo escribe quien quiera.
    """
    if not ruta or not ruta.startswith("/") or ruta.startswith("//"):
        return None
    try:
        coincidencia = resolve(ruta.split("?")[0])
    except Resolver404:
        return None
    if coincidencia.namespace != "panel":
        return None
    contexto = {"pantalla": coincidencia.url_name}
    kwargs = coincidencia.kwargs
    if coincidencia.url_name == "factura":
        if Documento.objects.filter(lote=kwargs.get("lote", ""), file_id=kwargs.get("file_id", "")).exists():
            contexto.update({"lote": kwargs["lote"], "file_id": kwargs["file_id"]})
    if coincidencia.url_name in ("proveedor", "proveedor_editar"):
        p = Proveedor.objects.filter(pk=kwargs.get("id")).first()
        contexto["proveedor"] = f"{p.nombre} ({p.codigo})" if p else f"nº {kwargs.get('id')}"
    return contexto


def _volver(request: HttpRequest, al_panel: bool = False) -> HttpResponse:
    """Vuelve a la pantalla de la que vino (`siguiente`), o a Preguntar. Solo rutas de esta web.

    Con `al_panel`, la dirección lleva #asistente para que el panel se abra con la conversación.
    """
    siguiente = request.POST.get("siguiente") or request.GET.get("siguiente") or ""
    if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}) or not siguiente.startswith("/"):
        siguiente = reverse("panel:preguntar")
    siguiente = siguiente.split("#")[0]
    if al_panel and not siguiente.startswith(reverse("panel:preguntar")):
        siguiente += "#asistente"
    return redirect(siguiente)


def preguntar(request: HttpRequest) -> HttpResponse:
    """El chat de Alberto: cada pregunta va al asistente y queda en la conversación abierta."""
    from web.panel.asistente import helmcode
    from web.panel.asistente.agente import responder

    if request.method == "POST":
        texto = (request.POST.get("pregunta") or "").strip()
        if not texto:
            return redirect("panel:preguntar")
        conversacion = conversacion_actual(request)
        historial = mensajes_de(conversacion)
        contexto = contexto_de(request.POST.get("ruta"))
        salida = responder(texto, historial, helmcode.completar, contexto)
        if conversacion is None:
            conversacion = Conversacion.objects.create(titulo=textwrap.shorten(texto, Conversacion.TITULO_MAX, placeholder="…"))
            abrir_conversacion(request, conversacion)
        else:
            conversacion.save(update_fields=["actualizada"])
        Pregunta.objects.create(
            conversacion=conversacion, texto=texto, respuesta=salida.texto, ok=salida.ok, error=salida.error,
            detalles={"fuentes": salida.fuentes, "enlaces": salida.enlaces, "propuestas": salida.propuestas},
            modelo=salida.modelo, tokens_in=salida.tokens_in, tokens_out=salida.tokens_out, segundos=salida.segundos,
        )
        pendientes_de(request).extend(p["nonce"] for p in salida.propuestas if p.get("nonce"))
        _guardar(request)
        if request.headers.get("HX-Request"):
            return render(request, "panel/_mensajes.html", {"mensajes": mensajes_de(conversacion)[-1:]})
    return render(request, "panel/preguntar.html", {"historial": historial_de(request), "pagina_actual": "preguntar"})


@require_POST
def nueva(request: HttpRequest) -> HttpResponse:
    """«Nueva»: la siguiente pregunta empieza otra conversación. Las anteriores se quedan en la lista."""
    abrir_conversacion(request, None)
    return _volver(request, al_panel=True)


def abrir(request: HttpRequest, id: int) -> HttpResponse:
    """Seguir una conversación de la lista: pasa a ser la abierta y se vuelve a donde estaba Alberto."""
    abrir_conversacion(request, get_object_or_404(Conversacion, pk=id))
    return _volver(request, al_panel=True)


@require_POST
def borrar(request: HttpRequest, id: int) -> HttpResponse:
    """La papelera: se van la conversación y sus preguntas; las acciones confirmadas se quedan (son traza)."""
    conversacion = get_object_or_404(Conversacion, pk=id)
    if request.session.get("conversacion") == conversacion.pk:
        abrir_conversacion(request, None)
    conversacion.delete()
    return _volver(request, al_panel=True)


@require_POST
def borrar_todas(request: HttpRequest) -> HttpResponse:
    abrir_conversacion(request, None)
    Conversacion.objects.all().delete()
    return _volver(request, al_panel=True)


@require_POST
def accion(request: HttpRequest) -> HttpResponse:
    """Alberto ha pulsado «Confirmar» o «No» en una propuesta del asistente.

    Confirmar: el token firmado lleva el tipo, los datos y el nonce; caducado, manipulado, de un tipo
    fuera de la lista, ya hecho o que no esté pendiente en la sesión, no se hace nada y se le dice. Si vale,
    se hace y queda registrado en la conversación; la propuesta desaparece y en su lugar queda «Hecho: …».
    No (`rechazar=1`): la propuesta se olvida sin hacer nada. Los avisos solo se enseñan, no se guardan.
    """
    from web.panel.asistente import acciones

    token = request.POST.get("token") or ""
    if request.POST.get("rechazar"):
        _olvidar_propuesta(request, acciones.nonce_de(token))
        mensaje = {"quien": "asistente", "aviso": "Vale, no se hace nada."}
    else:
        mensaje = _confirmar(request, token)
    _guardar(request)
    if request.headers.get("HX-Request"):
        return render(request, "panel/_mensajes.html", {"mensajes": [mensaje]})
    return redirect("panel:preguntar")


def _confirmar(request: HttpRequest, token: str) -> dict:
    from web.panel.asistente import acciones

    try:
        tipo, datos, nonce = acciones.leer_token(token)
    except signing.SignatureExpired:
        _olvidar_propuesta(request, acciones.nonce_de(token))
        return {"quien": "asistente", "aviso": "Esa propuesta ha caducado (valen diez minutos). Vuelva a pedírmelo."}
    except signing.BadSignature:
        return {"quien": "asistente", "aviso": "Esa propuesta no es válida. Vuelva a pedírmelo."}
    if nonce not in pendientes_de(request) or acciones.ya_hecha(nonce):
        _olvidar_propuesta(request, nonce)
        return {"quien": "asistente", "aviso": "Esa propuesta ya se hizo o se descartó. Si la quiere otra vez, vuelva a pedírmelo."}
    _olvidar_propuesta(request, nonce)  # antes de hacerla: aunque falle, no se reintenta sola
    hecha = acciones.ejecutar(tipo, datos, nonce, conversacion_actual(request))
    return _mensaje_hecho(hecha, acciones.enlace(hecha))
