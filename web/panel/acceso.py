"""La clave de acceso opcional: una sola clave compartida para cuando la web se publica con un túnel.

Sin `WEB_CLAVE` en el entorno no hace nada (el portátil, los tests). Con ella, quien abre la web ve una
pantalla que pide la clave; con la buena, una cookie firmada y no la vuelve a pedir en una jornada.
No es un sistema de usuarios: la web sigue siendo de Alberto y de nadie más.
"""
from __future__ import annotations

import secrets
import time

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template import loader
from django.utils.http import url_has_allowed_host_and_scheme

COOKIE = "acceso"
SAL = "acceso"
DURACION = 16 * 3600  # segundos: una jornada larga, y al día siguiente la vuelve a pedir
AVISO = "Esa clave no es. Pídasela a quien lleva el sistema."


class ClaveDeAcceso:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        clave = settings.WEB_CLAVE  # en cada petición, no al arrancar: así override_settings vale en los tests
        if not clave or request.path == "/salud/" or request.path.startswith(settings.STATIC_URL):
            return self.get_response(request)
        if request.get_signed_cookie(COOKIE, default=None, salt=SAL, max_age=DURACION) == "ok":
            return self.get_response(request)
        if request.headers.get("HX-Request"):
            # htmx no sabe pintar la puerta dentro de un trozo de página: que recargue y la vea entera.
            return HttpResponse(status=401, headers={"HX-Redirect": request.get_full_path()})
        if request.method == "POST" and "clave" in request.POST:
            return self._entrar(request, clave)
        return self._puerta(siguiente=request.get_full_path())

    def _entrar(self, request: HttpRequest, clave: str) -> HttpResponse:
        # El formulario no lleva csrf_token: esto responde antes de que CsrfViewMiddleware mire nada
        # (lo hace en process_view, y aquí no se llega a ninguna vista). La clave es el secreto.
        siguiente = request.POST.get("siguiente", "")
        if not secrets.compare_digest(request.POST.get("clave", "").encode(), clave.encode()):
            time.sleep(0.4)  # frena a quien pruebe claves a lo loco
            return self._puerta(siguiente=siguiente, error=AVISO)
        if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            siguiente = "/"
        respuesta = HttpResponseRedirect(siguiente)
        respuesta.set_signed_cookie(COOKIE, "ok", salt=SAL, max_age=DURACION, httponly=True, samesite="Lax", secure=request.is_secure())
        return respuesta

    @staticmethod
    def _puerta(siguiente: str, error: str = "") -> HttpResponse:
        # Sin el request: la puerta no toca la base de datos ni la sesión (los procesadores de contexto sí).
        html = loader.get_template("panel/acceso.html").render({"siguiente": siguiente, "error": error})
        return HttpResponse(html)
