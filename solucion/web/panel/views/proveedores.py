"""El maestro de Alberto, hecho por nosotros: proveedores y pedidos con un formulario sencillo."""
from __future__ import annotations

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from web.panel import consultas
from web.panel.forms import PedidoForm, ProveedorForm
from web.panel.models import Pedido, Proveedor


def lista(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    proveedores = Proveedor.objects.annotate(
        n_pedidos=Count("pedidos", distinct=True),
        n_revisar=Count("pedidos", filter=Q(pedidos__revisar=True), distinct=True),
    )
    if q:
        proveedores = proveedores.filter(Q(nombre__icontains=q) | Q(nif__icontains=q) | Q(codigo__icontains=q))
    return render(request, "panel/proveedores.html", {
        "proveedores": proveedores,
        "q": q,
        "total": Proveedor.objects.count(),
    })


def detalle(request: HttpRequest, id: int) -> HttpResponse:
    proveedor = get_object_or_404(Proveedor, pk=id)
    pedidos = list(proveedor.pedidos.all())
    ejecucion = consultas.ultima_ejecucion()
    facturas = []
    if ejecucion is not None and pedidos:
        decisiones = consultas.decisiones_de(ejecucion).filter(pedido__in=[p.numero for p in pedidos])
        facturas = [{"decision": d, "motivo": consultas.motivo_corto(d)} for d in decisiones]
    return render(request, "panel/proveedor.html", {
        "proveedor": proveedor,
        "pedidos": pedidos,
        "marcados": sum(1 for p in pedidos if p.revisar),
        "ejecucion": ejecucion,
        "facturas": facturas,
    })


def nuevo(request: HttpRequest) -> HttpResponse:
    return _formulario_proveedor(request, None)


def editar(request: HttpRequest, id: int) -> HttpResponse:
    return _formulario_proveedor(request, get_object_or_404(Proveedor, pk=id))


def editar_pedido(request: HttpRequest, id: int) -> HttpResponse:
    pedido = get_object_or_404(Pedido.objects.select_related("proveedor"), pk=id)
    return _formulario_pedido(request, pedido, pedido.proveedor)


def _formulario_proveedor(request: HttpRequest, proveedor: Proveedor | None) -> HttpResponse:
    if request.method == "POST":
        form = ProveedorForm(request.POST, instance=proveedor)
        if form.is_valid():
            guardado = form.save()
            messages.success(request, f"Guardado: {guardado.nombre}.")
            return redirect("panel:proveedor", id=guardado.id)
    else:
        form = ProveedorForm(instance=proveedor)
    return render(request, "panel/proveedor_form.html", {"form": form, "proveedor": proveedor})


def _formulario_pedido(request: HttpRequest, pedido: Pedido, proveedor: Proveedor) -> HttpResponse:
    if request.method == "POST":
        form = PedidoForm(request.POST, instance=pedido)
        if form.is_valid():
            guardado = form.save()
            messages.success(request, f"Guardado lo que ha dicho sobre el pedido {guardado.numero}.")
            return redirect("panel:proveedor", id=guardado.proveedor_id)
    else:
        form = PedidoForm(instance=pedido)
    return render(request, "panel/pedido_form.html", {"form": form, "pedido": pedido, "proveedor": proveedor})
