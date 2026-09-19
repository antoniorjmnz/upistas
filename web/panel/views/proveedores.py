"""El maestro de Alberto, hecho por nosotros: proveedores y pedidos con un formulario sencillo."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def lista(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Proveedores"})


def nuevo(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Nuevo proveedor"})


def detalle(request: HttpRequest, id: int) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Proveedor"})


def editar(request: HttpRequest, id: int) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Editar proveedor"})


def nuevo_pedido(request: HttpRequest, id: int) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Nuevo pedido"})


def editar_pedido(request: HttpRequest, id: int) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Editar pedido"})
