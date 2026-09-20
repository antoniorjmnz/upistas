from django.apps import AppConfig


class PanelConfig(AppConfig):
    name = "web.panel"
    verbose_name = "Panel de Alberto"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from web.panel.sincronizacion import arrancar_si_procede

        arrancar_si_procede()  # el vigilante de la sincronización constante, solo en el proceso que sirve la web
