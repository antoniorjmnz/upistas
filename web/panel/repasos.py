"""Repasar un lote desde la web: el pipeline en un hilo y el avance guardado en memoria.

DBOS solo arranca una vez por proceso: el primer repaso lo arranca dentro del propio proceso de
la web y los siguientes lo reutilizan. Se repasa un lote entero cada vez (la caché por huella hace
que las facturas ya leídas no se vuelvan a leer), y solo un repaso a la vez.
"""
from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

from django.utils import timezone

NORMA = "v3"

_candado = threading.Lock()
_repasos: dict[int, dict] = {}
_hilos: dict[int, threading.Thread] = {}
_ultimo_id = 0

_candado_dbos = threading.Lock()
_dbos_en_marcha = False


def estado(id: int) -> dict | None:
    """Cómo va un repaso, o None si ese id no existe."""
    return _repasos.get(id)


def lanzar(lote: str, rutas_nuevas: Sequence[Path] = ()) -> int:
    """Arranca el repaso de un lote en segundo plano y devuelve su id.

    Si ya hay uno en marcha no se arranca otro: se devuelve el que está corriendo.
    """
    global _ultimo_id

    rutas = _todas_las_rutas(lote, rutas_nuevas)
    with _candado:
        en_marcha = next((i for i, r in _repasos.items() if r["estado"] == "en_marcha"), None)
        if en_marcha is not None:
            return en_marcha
        _ultimo_id += 1
        id = _ultimo_id
        _repasos[id] = {
            "estado": "en_marcha", "leidos": 0, "total": len(rutas), "lote": lote,
            "ejecucion_id": None, "resumen": {}, "error": "",
            "empezado": timezone.now(), "terminado": None,
        }
        _hilos[id] = threading.Thread(target=_repasar, args=(id, lote, rutas), name=f"repaso-{id}", daemon=True)
    _hilos[id].start()
    return id


def _todas_las_rutas(lote: str, rutas_nuevas: Sequence[Path]) -> list[Path]:
    """Las facturas que el lote ya tenía más las que acaban de subir, sin repetir."""
    from web.panel.models import Documento

    rutas = [Path(r) for r in Documento.objects.filter(lote=lote).values_list("ruta", flat=True)]
    vistas = {str(r) for r in rutas}
    for nueva in rutas_nuevas:
        if str(nueva) not in vistas:
            vistas.add(str(nueva))
            rutas.append(Path(nueva))
    return rutas


def _arrancar_dbos() -> None:
    """DBOS, una sola vez por proceso: lo arranca el primer repaso que llega."""
    global _dbos_en_marcha
    from upistas.infra import pipeline

    with _candado_dbos:
        if not _dbos_en_marcha:
            pipeline.iniciar()
            _dbos_en_marcha = True


def _repasar(id: int, lote: str, rutas: list[Path]) -> None:
    from upistas.infra import django_setup, pipeline

    repaso = _repasos[id]
    try:
        _arrancar_dbos()
        informe = pipeline.procesar_lote(
            lote, rutas, NORMA, sincronizar=True,
            progreso=lambda leidos, total: repaso.update(leidos=leidos, total=total),
        )
        repaso.update(estado="terminado", ejecucion_id=informe.ejecucion.id, resumen=dict(informe.ejecucion.resumen or {}))
    except Exception as fallo:  # un repaso que se tuerce no puede tirar la web
        repaso.update(estado="error", error=str(fallo) or type(fallo).__name__)
    finally:
        repaso["terminado"] = timezone.now()
        django_setup.cerrar_conexion()
