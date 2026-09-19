"""Cada pasada por un lote: cifras, con qué datos se decidió, qué cambió y el outcomes.jsonl."""
from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render


def lista(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": "Ejecuciones"})


def detalle(request: HttpRequest, id: int) -> HttpResponse:
    return render(request, "panel/pronto.html", {"seccion": f"Ejecución {id}"})


def outcomes(request: HttpRequest, id: int) -> HttpResponse:
    raise Http404("pendiente")
