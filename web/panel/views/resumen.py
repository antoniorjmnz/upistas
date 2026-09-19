"""La portada: cómo va el lote de hoy."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def resumen(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Resumen"})
