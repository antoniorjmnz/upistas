from django.contrib import admin

from web.panel.models import (
    AsientoERP, Decision, Documento, Ejecucion, Importacion, Lectura, Pedido, Pregunta, Proveedor, RevisionHumana,
    SincronizacionERP, VersionERP,
)


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


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("file_id", "lote", "tipo", "paginas", "bytes", "sha256")
    list_filter = ("lote", "tipo")
    search_fields = ("file_id", "sha256")


@admin.register(Lectura)
class LecturaAdmin(admin.ModelAdmin):
    list_display = ("file_id", "lote", "ok", "metodo", "lector", "segundos", "tokens_in", "tokens_out", "coste_eur", "creada")
    list_filter = ("ok", "metodo", "lote")
    search_fields = ("file_id", "sha256")


@admin.register(Ejecucion)
class EjecucionAdmin(admin.ModelAdmin):
    list_display = ("id", "lote", "norma", "version_erp", "version_excel", "inicio", "fin", "estado")
    list_filter = ("lote", "norma", "estado")


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ("documento", "resultado", "pedido", "metodo", "motivo", "ejecucion")
    list_filter = ("resultado", "metodo", "ejecucion")
    search_fields = ("documento__file_id", "pedido", "motivo")


@admin.register(RevisionHumana)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ("documento", "resultado", "quien", "cuando", "comentario")
    list_filter = ("resultado", "quien")


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "nif", "iban", "ciudad", "condiciones_dias", "activo", "actualizado")
    list_filter = ("activo", "ciudad")
    search_fields = ("codigo", "nombre", "nif")


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("numero", "proveedor", "importe", "fecha", "revisar", "actualizado")
    list_filter = ("revisar", "proveedor")
    search_fields = ("numero", "proveedor__nombre", "proveedor__nif")


@admin.register(Importacion)
class ImportacionAdmin(admin.ModelAdmin):
    list_display = ("cuando", "ficheros", "nuevos", "cambiados", "invalidos")
    readonly_fields = ("cuando",)


@admin.register(Pregunta)
class PreguntaAdmin(admin.ModelAdmin):
    list_display = ("cuando", "texto", "ok", "tokens_in", "tokens_out", "segundos")
    list_filter = ("ok",)
    search_fields = ("texto", "respuesta", "error")
    readonly_fields = ("cuando",)
