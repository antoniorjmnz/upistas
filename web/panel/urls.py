from django.urls import path

from web.panel.views import cuenta, ejecuciones, erp, facturas, resumen, revision

app_name = "panel"

urlpatterns = [
    path("", resumen.resumen, name="inicio"),
    path("entrar/", cuenta.entrar, name="entrar"),
    path("salir/", cuenta.salir, name="salir"),
    path("facturas/", facturas.lista, name="facturas"),
    path("facturas/<str:lote>/<str:file_id>/", facturas.detalle, name="factura"),
    path("facturas/<str:lote>/<str:file_id>/pdf/", facturas.pdf, name="factura_pdf"),
    path("facturas/<str:lote>/<str:file_id>/revisar/", revision.revisar, name="revisar"),
    path("revisar/", revision.cola, name="cola"),
    path("ejecuciones/", ejecuciones.lista, name="ejecuciones"),
    path("ejecuciones/<int:id>/", ejecuciones.detalle, name="ejecucion"),
    path("ejecuciones/<int:id>/outcomes.jsonl", ejecuciones.outcomes, name="outcomes"),
    path("erp/", erp.conexion, name="conexion"),
    path("erp/sincronizar/", erp.sincronizar, name="sincronizar"),
    path("erp/asientos/", erp.asientos, name="asientos"),
    path("erp/cambios/<str:de>/<str:a>/", erp.cambios, name="cambios"),
]
