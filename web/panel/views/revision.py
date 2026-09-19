"""Lo que Alberto tiene que mirar: la cola de facturas escaladas y su decisión sobre cada una."""
from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from web.panel import consultas
from web.panel.models import Decision, RevisionHumana

POR_PAGINA = 25
RESULTADOS = ("PAGAR", "NO_PAGAR")
MAX_COMENTARIO = 500
SIN_LEER = "No se pudo leer"


def _motivo_corto(decision: Decision) -> str:
    """El motivo principal en palabras: la primera comprobación que falla, o que no se pudo leer."""
    reglas = (decision.outcome or {}).get("reglas") or []
    if not reglas:
        return SIN_LEER
    fallan = [r for r in reglas if not r.get("ok")]
    if not fallan:
        return "Hay dudas con los datos"
    return consultas.nombre_regla(fallan[0].get("id", ""))


def _ordenadas(decisiones: list[Decision]) -> list[tuple[str, Decision]]:
    """Agrupa por motivo para resolver en cadena: primero el que más se repite, lo ilegible al final."""
    motivos = [(_motivo_corto(d), d) for d in decisiones]
    cuantas: dict[str, int] = {}
    for motivo, _ in motivos:
        cuantas[motivo] = cuantas.get(motivo, 0) + 1
    return sorted(motivos, key=lambda p: (p[0] == SIN_LEER, -cuantas[p[0]], p[0], p[1].documento.file_id))


def _grupos(motivos: list[tuple[str, Decision]], revisiones: dict[int, RevisionHumana]) -> list[dict]:
    """Las filas de la página, con lo leído de cada factura. Una sola consulta de lecturas."""
    lecturas = consultas.lecturas_por_sha(d.documento.sha256 for _, d in motivos)
    grupos: list[dict] = []
    for motivo, decision in motivos:
        campos = consultas.campos(lecturas.get(decision.documento.sha256))
        if not grupos or grupos[-1]["titulo"] != motivo:
            grupos.append({"titulo": motivo, "filas": []})
        grupos[-1]["filas"].append({
            "decision": decision,
            "revision": revisiones.get(decision.documento_id),
            "proveedor": campos.get("proveedor_nombre"),
            "total": campos.get("total"),
        })
    return grupos


def _texto_vacio(estado: str, q: str, hay_ejecucion: bool) -> str:
    if not hay_ejecucion:
        return "Todavía no se ha procesado ningún lote de facturas."
    if q:
        return "Ninguna factura coincide con lo que ha escrito."
    if estado == "revisadas":
        return "Todavía no ha revisado ninguna factura de este lote."
    if estado == "todas":
        return "En este lote no hay ninguna factura para revisar."
    return "No hay nada pendiente de revisar."


def cola(request: HttpRequest) -> HttpResponse:
    lote = request.GET.get("lote") or None
    ejecucion = consultas.ultima_ejecucion(lote)
    estado = request.GET.get("estado") or "pendientes"
    q = (request.GET.get("q") or "").strip()

    if ejecucion is None:
        escaladas, revisiones = Decision.objects.none(), {}
        n_pendientes = n_revisadas = n_escaladas = 0
    else:
        escaladas = consultas.decisiones_de(ejecucion).filter(resultado="ESCALAR")
        revisiones = consultas.revisiones_por_documento(ejecucion.lote)
        n_pendientes = consultas.pendientes_de_revision(ejecucion).count()
        n_escaladas = escaladas.count()
        n_revisadas = n_escaladas - n_pendientes

        if estado == "revisadas":
            escaladas = escaladas.filter(documento_id__in=revisiones)
        elif estado != "todas":
            estado = "pendientes"
            escaladas = consultas.pendientes_de_revision(ejecucion)
        if q:
            escaladas = escaladas.filter(
                Q(documento__file_id__icontains=q) | Q(pedido__icontains=q) | Q(motivo__icontains=q)
            )

    pagina = Paginator(_ordenadas(list(escaladas)), POR_PAGINA).get_page(request.GET.get("pagina"))
    ctx = {
        "lotes": consultas.lotes(),
        "lote": ejecucion.lote if ejecucion else "",
        "estado": estado,
        "q": q,
        "pagina": pagina,
        "grupos": _grupos(list(pagina), revisiones),
        "vacio": _texto_vacio(estado, q, ejecucion is not None),
        "n_pendientes": n_pendientes,
        "n_revisadas": n_revisadas,
        "n_escaladas": n_escaladas,
    }
    plantilla = "panel/_revisar_lista.html" if request.headers.get("HX-Request") else "panel/revisar.html"
    return render(request, plantilla, ctx)


@require_POST
def revisar(request: HttpRequest, lote: str, file_id: str) -> HttpResponse:
    resultado = (request.POST.get("resultado") or "").strip()
    comentario = (request.POST.get("comentario") or "").strip()
    if resultado not in RESULTADOS:
        return HttpResponseBadRequest("Diga si la factura se paga o no se paga.")
    if len(comentario) > MAX_COMENTARIO:
        return HttpResponseBadRequest(f"El comentario no puede pasar de {MAX_COMENTARIO} letras.")

    ejecucion = consultas.ultima_ejecucion(lote)
    if ejecucion is None:
        raise Http404("Ese lote todavía no se ha procesado")
    decision = get_object_or_404(
        Decision.objects.select_related("documento"),
        ejecucion=ejecucion, documento__lote=lote, documento__file_id=file_id,
    )
    # Las revisiones anteriores se quedan: son el historial de lo que Alberto fue decidiendo.
    revision = RevisionHumana.objects.create(
        documento=decision.documento, decision=decision, quien="Alberto",
        resultado=resultado, comentario=comentario,
    )
    if request.headers.get("HX-Request"):
        return render(request, "panel/_revisar_form.html", {"decision": decision, "revision": revision})
    messages.success(request, f"Guardado: {file_id} queda como «{consultas.ETIQUETA[resultado]}».")
    return redirect("panel:factura", lote=lote, file_id=file_id)
