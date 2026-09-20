"""Las páginas de error, en la piel de la web y en español llano, y la comprobación de salud del despliegue.

Sin DEBUG, Django enseñaría sus páginas grises en inglés; estas son las que ve Alberto. La de 500 no toca
la base de datos ni el contexto de las pantallas, porque puede ser justo eso lo que ha fallado.
"""
from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template import loader
from django.views.decorators.http import require_GET


def no_existe(request: HttpRequest, exception=None) -> HttpResponse:
    return render(request, "panel/404.html", status=404)


def algo_fallo(request: HttpRequest) -> HttpResponse:
    return HttpResponse(loader.get_template("panel/500.html").render(), status=500)


def no_permitido(request: HttpRequest, exception=None) -> HttpResponse:
    return render(request, "panel/403.html", {"por_formulario": False}, status=403)


def csrf_fallo(request: HttpRequest, reason: str = "") -> HttpResponse:
    """Un formulario llegó sin su marca de seguridad: normalmente la página llevaba abierta demasiado tiempo."""
    return render(request, "panel/403.html", {"por_formulario": True}, status=403)


@require_GET
def salud(request: HttpRequest) -> HttpResponse:
    """Para el comprobador del despliegue: «ok» en texto llano si la web responde y la base de datos contesta."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001 - da igual qué haya fallado: la web no está bien
        return HttpResponse("sin base de datos", content_type="text/plain; charset=utf-8", status=503)
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")
