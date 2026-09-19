from django.contrib import admin

from web.panel.models import AsientoERP, SincronizacionERP, VersionERP


@admin.register(SincronizacionERP)
class SincronizacionAdmin(admin.ModelAdmin):
    list_display = ("inicio", "ok", "version", "n_asientos", "reintentos_ora", "esperas_429", "relogins", "segundos", "nuevos", "modificados", "eliminados")
    list_filter = ("ok",)


@admin.register(VersionERP)
class VersionAdmin(admin.ModelAdmin):
    list_display = ("version", "creada", "n_asientos", "lote2_cargado")


@admin.register(AsientoERP)
class AsientoAdmin(admin.ModelAdmin):
    list_display = ("asiento_id", "pedido", "proveedor_id", "nif", "importe", "fecha", "estado", "version")
    list_filter = ("estado", "proveedor_id", "version")
    search_fields = ("asiento_id", "pedido", "nif")
