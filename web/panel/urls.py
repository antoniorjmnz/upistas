from django.urls import path

from web.panel import views

app_name = "panel"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("erp/", views.conexion, name="conexion"),
    path("erp/sincronizar/", views.sincronizar, name="sincronizar"),
    path("erp/asientos/", views.asientos, name="asientos"),
    path("erp/cambios/<str:de>/<str:a>/", views.cambios, name="cambios"),
]
