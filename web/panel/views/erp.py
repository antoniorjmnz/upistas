"""Pantallas de Alberto. Leen nuestra base de datos; el ERP solo lo toca la sincronización."""
from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.versiones import diferencias
from web.panel.models import AsientoERP, SincronizacionERP, VersionERP


def _copia_en_uso() -> SincronizacionERP | None:
    return SincronizacionERP.objects.filter(ok=True).select_related("version").first()


def inicio(request: HttpRequest) -> HttpResponse:
    return redirect("panel:conexion")


def _contexto_conexion() -> dict:
    ultima = SincronizacionERP.objects.select_related("version").first()
    en_uso = _copia_en_uso()
    estados = {}
    if en_uso and en_uso.version_id:
        filas = AsientoERP.objects.filter(version_id=en_uso.version_id).values("estado").annotate(n=Count("id"))
        estados = {f["estado"]: f["n"] for f in filas}
    historial = list(SincronizacionERP.objects.select_related("version")[:20])
    # Para enlazar "qué cambió": la versión que había justo antes de cada sincronización correcta.
    anterior_de, previa, primera = {}, None, None
    for s in SincronizacionERP.objects.filter(ok=True).order_by("inicio", "id").only("id", "version_id"):
        primera = primera or s.id
        anterior_de[s.id] = previa if previa != s.version_id else None
        previa = s.version_id
    for s in historial:
        s.version_anterior = anterior_de.get(s.id)
        s.es_primera = s.id == primera
    return {
        "ultima": ultima,
        "en_uso": en_uso,
        "fallo_reciente": ultima is not None and not ultima.ok,
        "pendientes": estados.get("PENDIENTE", 0),
        "pagados": estados.get("PAGADA", 0),
        "historial": historial,
    }


def conexion(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/conexion.html", _contexto_conexion())


@require_POST
def sincronizar(request: HttpRequest) -> HttpResponse:
    from upistas.infra import contenedor

    sincronizar_erp(contenedor.cliente_erp(), AlmacenERPDjango())
    if request.headers.get("HX-Request"):
        return render(request, "panel/_conexion_estado.html", _contexto_conexion())
    return redirect("panel:conexion")


def asientos(request: HttpRequest) -> HttpResponse:
    versiones = VersionERP.objects.all()
    en_uso = _copia_en_uso()
    version = request.GET.get("version") or (en_uso.version_id if en_uso else None)
    q = (request.GET.get("q") or "").strip()
    estado = request.GET.get("estado") or ""

    qs = AsientoERP.objects.filter(version_id=version) if version else AsientoERP.objects.none()
    total_version = qs.count()
    if q:
        qs = qs.filter(Q(asiento_id__icontains=q) | Q(pedido__icontains=q) | Q(proveedor_id__iexact=q) | Q(nif__icontains=q))
    if estado:
        qs = qs.filter(estado=estado)
    pagina = Paginator(qs.order_by("pedido"), 25).get_page(request.GET.get("pagina"))

    ctx = {
        "versiones": versiones,
        "version": version,
        "en_uso": en_uso,
        "q": q,
        "estado": estado,
        "pagina": pagina,
        "total_version": total_version,
        "encontrados": pagina.paginator.count,
    }
    plantilla = "panel/_asientos_tabla.html" if request.headers.get("HX-Request") else "panel/asientos.html"
    return render(request, plantilla, ctx)


def cambios(request: HttpRequest, de: str, a: str) -> HttpResponse:
    antes, despues = get_object_or_404(VersionERP, pk=de), get_object_or_404(VersionERP, pk=a)
    almacen = AlmacenERPDjango()
    d = diferencias(almacen.asientos(antes.pk), almacen.asientos(despues.pk))
    nuevos = AsientoERP.objects.filter(version=despues, asiento_id__in=d.nuevos)
    eliminados = AsientoERP.objects.filter(version=antes, asiento_id__in=d.eliminados)
    return render(request, "panel/cambios.html", {
        "antes": antes, "despues": despues, "d": d, "nuevos": nuevos, "eliminados": eliminados,
        "pedidos": sorted(d.pedidos_afectados),
    })
