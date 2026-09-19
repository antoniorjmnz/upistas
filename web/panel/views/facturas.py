"""Las facturas del lote: lista con filtros, detalle con toda su traza y el PDF original."""
from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render


def lista(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Facturas"})


def detalle(request: HttpRequest, lote: str, file_id: str) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": f"Factura {file_id}"})


def pdf(request: HttpRequest, lote: str, file_id: str) -> HttpResponse:
    raise Http404("pendiente")
