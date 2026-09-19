"""Preguntar: Alberto escribe y la web contesta con los datos que tiene (#39, ver docs/asistente.md)."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def preguntar(request: HttpRequest) -> HttpResponse:
    return render(request, "panel/preguntar.html")
