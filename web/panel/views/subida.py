"""Subir facturas y repasar desde la web: los PDF se guardan aquí y el pipeline los decide."""
from __future__ import annotations

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from web.panel import almacen, consultas, repasos

NUEVO = "__nuevo__"  # la opción "Nuevo lote…" del desplegable
POR_DEFECTO = "lote1"


def subir(request: HttpRequest) -> HttpResponse:
    """La pantalla de subir facturas y, con ?repaso=N, cómo va el repaso que se acaba de lanzar."""
    if request.method == "POST":
        return _guardar_y_repasar(request)

    actual = _lote_actual()
    lotes = consultas.lotes()
    ctx = {
        "lotes": [{"id": l, "nombre": consultas.nombre_lote(l)} for l in ([actual] if actual not in lotes else []) + lotes],
        "lote": actual,
        "nuevo": NUEVO,
    }
    pedido = request.GET.get("repaso") or ""
    repaso = repasos.estado(int(pedido)) if pedido.isdigit() else None
    if repaso is not None:
        ctx |= {"repaso": repaso, "repaso_id": int(pedido)}
    return render(request, "panel/subir.html", ctx)


@require_POST
def repasar(request: HttpRequest) -> HttpResponse:
    """Repasar otra vez el lote, sin subir nada nuevo."""
    lote = (request.POST.get("lote") or "").strip() or _lote_actual()
    return _a_la_pantalla(repasos.lanzar(lote))


def estado(request: HttpRequest, id: int) -> HttpResponse:
    """El trozo de pantalla que dice cómo va el repaso. Se pide cada segundo hasta que termina."""
    repaso = repasos.estado(id)
    if repaso is None:
        raise Http404("Ese repaso no existe.")
    return render(request, "panel/_repaso.html", {"repaso": repaso, "repaso_id": id})


def _lote_actual() -> str:
    ejecucion = consultas.ultima_ejecucion()
    return ejecucion.lote if ejecucion else POR_DEFECTO


def _lote_elegido(request: HttpRequest) -> str:
    elegido = (request.POST.get("lote") or "").strip()
    if elegido == NUEVO:
        elegido = (request.POST.get("lote_nuevo") or "").strip()
    return elegido[:40] or _lote_actual()


def _a_la_pantalla(id: int | None = None) -> HttpResponse:
    """Después de subir se vuelve a la pantalla con un GET (303), para que recargar no repita la subida."""
    respuesta = redirect(reverse("panel:subir") + (f"?repaso={id}" if id else ""))
    respuesta.status_code = 303
    return respuesta


def _guardar_y_repasar(request: HttpRequest) -> HttpResponse:
    lote = _lote_elegido(request)
    ficheros = request.FILES.getlist("facturas")
    if not ficheros:
        messages.error(request, "No ha elegido ninguna factura.", extra_tags="mal")
        return _a_la_pantalla()

    guardado = almacen.guardar(lote, ficheros)
    for error in guardado.errores:
        messages.warning(request, error, extra_tags="ojo")
    if not guardado.facturas:
        return _a_la_pantalla()

    cuantas = "1 factura" if len(guardado.facturas) == 1 else f"{len(guardado.facturas)} facturas"
    messages.success(request, f"Hemos guardado {cuantas} en {consultas.nombre_lote(lote).lower()}. Empezamos a repasar.", extra_tags="bien")
    return _a_la_pantalla(repasos.lanzar(lote, [f.ruta for f in guardado.facturas]))
