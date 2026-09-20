"""Mantener la sincronización con el ERP constante: si Alberto lo pide, la web trae sola el ERP cada minuto.

Como en repasos.py, es un hilo daemon dentro del proceso de la web. El interruptor vive en la base de datos
(`Ajuste`, clave `erp_constante`) para que sobreviva a reinicios; el hilo solo arranca en el proceso que sirve
la web (el hijo de runserver o gunicorn), nunca bajo pytest ni en los comandos de manage.py, y nunca muere:
un ERP caído se apunta como sincronización fallida y se vuelve a intentar en la siguiente vuelta.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta

from django.utils import timezone

log = logging.getLogger(__name__)

CADA_S = int(os.getenv("ERP_SYNC_CADA_S", "60"))  # segundos entre comprobaciones del ERP
CLAVE = "erp_constante"

_candado = threading.Lock()
_hilo: threading.Thread | None = None
_sincronizando = threading.Lock()  # una sincronización a la vez: el botón y el hilo no se pisan


def esta_activa() -> bool:
    from web.panel.models import Ajuste

    return Ajuste.leer(CLAVE) == "1"


def activar(si: bool) -> None:
    from web.panel.models import Ajuste

    Ajuste.guardar(CLAVE, "1" if si else "")


def sincronizar_una_vez(automatica: bool = True):
    """Una sincronización con el ERP en vivo; las del hilo van marcadas como automáticas."""
    from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
    from upistas.aplicacion.sincronizar_erp import sincronizar_erp
    from upistas.infra import contenedor

    with _sincronizando:
        return sincronizar_erp(contenedor.cliente_erp(), AlmacenERPDjango(automatica=automatica))


def toca_sincronizar(ahora: datetime | None = None) -> bool:
    """Está activa y la última sincronización (bien o mal) empezó hace más de CADA_S segundos, o no hay ninguna."""
    from web.panel.models import SincronizacionERP

    if not esta_activa():
        return False
    ultima = SincronizacionERP.objects.only("inicio").first()
    if ultima is None:
        return True
    return (ahora or timezone.now()) - ultima.inicio > timedelta(seconds=CADA_S)


def vigilar() -> None:
    """El bucle del hilo: mira si toca, sincroniza y suelta la conexión a la base de datos en cada vuelta."""
    from django.db import connection

    pausa = max(1.0, CADA_S / 4)
    while True:
        try:
            if toca_sincronizar(timezone.now()):
                s = sincronizar_una_vez()
                if not s.ok:
                    log.warning("La sincronización constante no pudo con el ERP: %s", s.error)
        except Exception:  # el hilo no muere por un fallo: se apunta y se vuelve a intentar
            log.exception("La sincronización constante con el ERP falló")
        finally:
            connection.close()
        time.sleep(pausa)


def _sirviendo_la_web() -> bool:
    """Solo el proceso que atiende peticiones: el hijo de runserver (RUN_MAIN), runserver --noreload o gunicorn."""
    argv = sys.argv
    if argv and argv[0].endswith("gunicorn"):
        return True
    if "runserver" in argv:
        return os.environ.get("RUN_MAIN") == "true" or "--noreload" in argv
    return False


def arrancar_si_procede() -> bool:
    """Arranca el vigilante si este proceso sirve la web y aún no está en marcha. Devuelve si lo ha arrancado."""
    global _hilo

    if not _sirviendo_la_web():
        return False
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return False
        _hilo = threading.Thread(target=vigilar, name="erp-constante", daemon=True)
        _hilo.start()
    return True
