"""La portada: cómo va el lote de hoy."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from web.panel import consultas
from web.panel.consultas import cifras, nombre_lote
from web.panel.models import SincronizacionERP

EN_PORTADA = 5  # cuántos cambios y cuántos pendientes se enseñan sin salir de la portada


def _estado_del_erp() -> dict:
    """Si la última conexión con el ERP falló, con qué copia estamos trabajando mientras tanto."""
    ultima = SincronizacionERP.objects.first()
    if ultima is None or ultima.ok:
        return {}
    return {"erp_fallo": ultima, "erp_copia": SincronizacionERP.objects.filter(ok=True).first()}


def _importes(decisiones: list, lecturas: dict) -> dict:
    """Cuánto dinero hay en cada montón, según el total que se leyó en cada factura."""
    suma: dict[str, float] = {}
    for d in decisiones:
        total = consultas.campos(lecturas.get(d.documento.sha256)).get("total")
        if total is not None:
            suma[d.resultado] = suma.get(d.resultado, 0.0) + float(total)
    return suma


def resumen(request: HttpRequest) -> HttpResponse:
    lotes = consultas.lotes()
    pedido = request.GET.get("lote") or ""
    lote = pedido if pedido in lotes else ""
    ejecucion = consultas.ultima_ejecucion(lote or None)
    ctx = {
        "lotes": [{"id": l, "nombre": nombre_lote(l)} for l in lotes],
        "ejecucion": ejecucion,
        **_estado_del_erp(),
    }
    if ejecucion is None:
        return render(request, "panel/resumen.html", ctx)

    decisiones = list(consultas.decisiones_de(ejecucion))
    lecturas = consultas.lecturas_por_sha(d.documento.sha256 for d in decisiones)
    revisiones = consultas.revisiones_por_documento(ejecucion.lote)
    pendientes = list(consultas.pendientes_de_revision(ejecucion))
    for d in pendientes[:EN_PORTADA]:  # quién es y cuánto pide, para que Alberto lo reconozca de un vistazo
        datos = consultas.campos(lecturas.get(d.documento.sha256))
        d.proveedor, d.total = datos.get("proveedor_nombre"), datos.get("total")
        d.motivo_corto = consultas.motivo_corto(d)
    anterior, cambios = consultas.cambios_respecto_a_la_anterior(ejecucion)
    importes = _importes(decisiones, lecturas)
    return render(request, "panel/resumen.html", ctx | {
        "cifras": cifras(ejecucion),
        "revisadas": sum(1 for d in decisiones if d.resultado == "ESCALAR" and d.documento_id in revisiones),
        "pendientes": pendientes[:EN_PORTADA],
        "por_revisar": len(pendientes),
        "a_pagar": importes.get("PAGAR", 0),
        "en_revision": importes.get("ESCALAR", 0),
        "anterior": anterior,
        "cambios": cambios,
        "primeros_cambios": cambios[:EN_PORTADA],
    })
