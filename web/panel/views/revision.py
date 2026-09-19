"""Lo que Alberto tiene que mirar: la cola de facturas escaladas y su decisión sobre cada una."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


def cola(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Para revisar"})


@require_POST
def revisar(request: HttpRequest, lote: str, file_id: str) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Revisión"})
