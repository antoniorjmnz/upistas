from django.contrib import admin
from django.urls import include, path

from web.panel.views import errores

urlpatterns = [
    path("admin/", admin.site.urls),
    path("salud/", errores.salud, name="salud"),
    path("", include("web.panel.urls")),
]

# Las páginas de error propias (sin DEBUG); las de CSRF las apunta CSRF_FAILURE_VIEW en settings.
handler404 = errores.no_existe
handler500 = errores.algo_fallo
handler403 = errores.no_permitido
