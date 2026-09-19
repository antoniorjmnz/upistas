from django.urls import path

from web.panel.views import chat, ejecuciones, erp, facturas, importar, proveedores, resumen, revision, subida

app_name = "panel"

urlpatterns = [
    path("", resumen.resumen, name="inicio"),
    path("subir/", subida.subir, name="subir"),
    path("repasar/", subida.repasar, name="repasar"),
    path("repasos/<int:id>/estado/", subida.estado, name="repaso_estado"),
    path("proveedores/", proveedores.lista, name="proveedores"),
    path("proveedores/nuevo/", proveedores.nuevo, name="proveedor_nuevo"),
    path("proveedores/importar/", importar.importar, name="proveedor_importar"),
    path("proveedores/importar/<str:token>/", importar.vista_previa, name="proveedor_importar_previa"),
    path("proveedores/<int:id>/", proveedores.detalle, name="proveedor"),
    path("proveedores/<int:id>/editar/", proveedores.editar, name="proveedor_editar"),
    path("pedidos/<int:id>/editar/", proveedores.editar_pedido, name="pedido_editar"),
    path("facturas/", facturas.lista, name="facturas"),
    path("facturas/<str:lote>/<str:file_id>/", facturas.detalle, name="factura"),
    path("facturas/<str:lote>/<str:file_id>/pdf/", facturas.pdf, name="factura_pdf"),
    path("facturas/<str:lote>/<str:file_id>/pdf-marcado/", facturas.pdf_marcado, name="factura_pdf_marcado"),
    path("facturas/<str:lote>/<str:file_id>/revisar/", revision.revisar, name="revisar"),
    path("revisar/", revision.cola, name="cola"),
    path("preguntar/", chat.preguntar, name="preguntar"),
    path("asistente/accion/", chat.accion, name="asistente_accion"),
    path("asistente/nueva/", chat.nueva, name="asistente_nueva"),
    path("asistente/conversaciones/<int:id>/", chat.abrir, name="asistente_abrir"),
    path("asistente/conversaciones/<int:id>/borrar/", chat.borrar, name="asistente_borrar"),
    path("asistente/conversaciones/borrar-todas/", chat.borrar_todas, name="asistente_borrar_todas"),
    path("ejecuciones/", ejecuciones.lista, name="ejecuciones"),
    path("ejecuciones/<int:id>/", ejecuciones.detalle, name="ejecucion"),
    path("ejecuciones/<int:id>/outcomes.jsonl", ejecuciones.outcomes, name="outcomes"),
    path("erp/", erp.conexion, name="conexion"),
    path("erp/sincronizar/", erp.sincronizar, name="sincronizar"),
    path("erp/asientos/", erp.asientos, name="asientos"),
    path("erp/cambios/<str:de>/<str:a>/", erp.cambios, name="cambios"),
]
