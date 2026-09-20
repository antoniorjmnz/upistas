"""Lo que Alberto tiene que mirar: la cola de facturas escaladas y su decisión sobre cada una."""
from __future__ import annotations

from urllib.parse import urlencode

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


def _ordenadas(decisiones: list[Decision]) -> list[tuple[str, Decision]]:
    """Agrupa por motivo para resolver en cadena: primero el que más se repite, lo ilegible al final."""
    motivos = [(consultas.motivo_corto(d), d) for d in decisiones]
    cuantas: dict[str, int] = {}
    for motivo, _ in motivos:
        cuantas[motivo] = cuantas.get(motivo, 0) + 1
    return sorted(motivos, key=lambda p: (p[0] == consultas.SIN_LEER, -cuantas[p[0]], p[0], p[1].documento.file_id))


def _grupos(motivos: list[tuple[str, Decision]], revisiones: dict[int, RevisionHumana]) -> list[dict]:
    """Las filas de la página, con lo leído de cada factura. Una sola consulta de lecturas."""
    lecturas = consultas.lecturas_por_sha(d.documento.sha256 for _, d in motivos)
    por_nif = consultas.nombres_por_nif()
    grupos: list[dict] = []
    for motivo, decision in motivos:
        campos = consultas.campos(lecturas.get(decision.documento.sha256))
        if not grupos or grupos[-1]["titulo"] != motivo:
            grupos.append({"titulo": motivo, "filas": []})
        grupos[-1]["filas"].append({
            "decision": decision,
            "revision": revisiones.get(decision.documento_id),
            "proveedor": consultas.nombre_proveedor(campos, por_nif),
            "total": campos.get("total"),
            "marcable": consultas.hay_algo_que_marcar(decision),  # sin nada que rodear, el botón sobra
        })
    return grupos


def _vacio(estado: str, q: str, hay_filtro: bool, hay_ejecucion: bool) -> dict:
    """Qué decirle cuando no hay nada que enseñar, sin que parezca un error."""
    if not hay_ejecucion:
        return {"titulo": "Todavía no hay facturas", "detalle": "En cuanto se pase el primer lote verá aquí lo que tiene que decidir."}
    if hay_filtro:
        return {"titulo": "Ninguna factura coincide", "detalle": "Pruebe con otro proveedor u otras fechas, o quite los filtros."}
    if q:
        return {"titulo": "No hay ninguna factura con eso", "detalle": "Pruebe con el nombre del fichero o con el número del pedido."}
    if estado == "decididas":
        return {"titulo": "Todavía no ha decidido ninguna", "detalle": "Aquí irán apareciendo según diga si se pagan o no."}
    return {"titulo": "No le queda nada por decidir", "detalle": "Todas las facturas que el sistema no supo resolver ya tienen su decisión."}


def _hoy():
    from datetime import date

    from upistas.config import settings as ajustes

    return ajustes.hoy or date.today()


def cola(request: HttpRequest) -> HttpResponse:
    lote = request.GET.get("lote") or None
    ejecucion = consultas.ultima_ejecucion(lote)
    estado = "decididas" if request.GET.get("estado") == "decididas" else "pendientes"
    q = (request.GET.get("q") or "").strip()
    proveedores = consultas.proveedores_para_filtro()
    proveedor = (request.GET.get("proveedor") or "").strip()
    if proveedor not in dict(proveedores):  # un código que ya no está en el maestro no filtra nada
        proveedor = ""
    desde = consultas.fecha_o_nada(request.GET.get("desde"))
    hasta = consultas.fecha_o_nada(request.GET.get("hasta"))
    desde_texto = desde.isoformat() if desde else ""
    hasta_texto = hasta.isoformat() if hasta else ""
    hay_filtro = bool(proveedor) or desde is not None or hasta is not None

    if ejecucion is None:
        escaladas, revisiones = Decision.objects.none(), {}
        n_pendientes = n_decididas = n_escaladas = 0
    else:
        revisiones = consultas.revisiones_por_documento(ejecucion.lote)
        n_escaladas = consultas.decisiones_de(ejecucion).filter(resultado="ESCALAR").count()
        n_pendientes = consultas.pendientes_de_revision(ejecucion).count()
        n_decididas = n_escaladas - n_pendientes

        if estado == "decididas":
            escaladas = consultas.decisiones_de(ejecucion).filter(resultado="ESCALAR", documento_id__in=revisiones)
        else:
            escaladas = consultas.pendientes_de_revision(ejecucion)
        if q:
            escaladas = escaladas.filter(
                Q(documento__file_id__icontains=q) | Q(pedido__icontains=q) | Q(motivo__icontains=q)
            )
        escaladas = consultas.filtrar_decisiones(escaladas, proveedor=proveedor, fecha_desde=desde, fecha_hasta=hasta)

    pagina = Paginator(_ordenadas(list(escaladas)), POR_PAGINA).get_page(request.GET.get("pagina"))
    lotes = consultas.lotes()
    nombre_proveedor = dict(proveedores).get(proveedor, "") if proveedor else ""
    es_htmx = bool(request.headers.get("HX-Request"))
    ctx = {
        "lotes": lotes,
        "varios_lotes": len(lotes) > 1,
        "lote": ejecucion.lote if ejecucion else "",
        "estado": estado,
        "q": q,
        "proveedores": proveedores,
        "proveedor": proveedor,
        "proveedor_nombre": nombre_proveedor,
        "desde": desde_texto,
        "hasta": hasta_texto,
        "consulta": urlencode({
            "q": q, "lote": ejecucion.lote if ejecucion else "",
            "proveedor": proveedor, "desde": desde_texto, "hasta": hasta_texto,
        }),
        "sin_filtros": urlencode({"q": q, "lote": ejecucion.lote if ejecucion else ""}),
        "hay_filtro": hay_filtro,
        "atajos": consultas.atajos_de_fecha(_hoy()),
        "pagina": pagina,
        "grupos": _grupos(list(pagina), revisiones),
        "vacio": _vacio(estado, q, hay_filtro, ejecucion is not None),
        "n_pendientes": n_pendientes,
        "n_decididas": n_decididas,
        "n_escaladas": n_escaladas,
        "avance": round(100 * n_decididas / n_escaladas) if n_escaladas else 0,
        "oob": es_htmx,  # con htmx los chips vuelven con la lista para quedarse al día
    }
    return render(request, "panel/_revisar_lista.html" if es_htmx else "panel/revisar.html", ctx)


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
