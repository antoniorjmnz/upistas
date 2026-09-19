"""Arranca Django fuera de la web (CLI, pipeline) para usar la misma base de datos."""
from __future__ import annotations

import os

_listo = False


def configurar(migrar: bool = True) -> None:
    global _listo
    if _listo:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()
    if migrar:
        from django.core.management import call_command

        call_command("migrate", verbosity=0, interactive=False)
    _listo = True
