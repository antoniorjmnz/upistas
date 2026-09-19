"""Subir facturas y repasar desde la web: los PDF se guardan aquí y el pipeline los decide."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


def subir(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Subir facturas"})


@require_POST
def repasar(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Repasar"})


def estado(request: HttpRequest, id: int) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Repaso"})
