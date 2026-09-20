"""Caso de uso: traer el ERP de Alberto a nuestra copia local.

Se descarga entero una vez (el manual lo recomienda: el bridge es lento y se cae) y se guarda
como una versión. Si el contenido no ha cambiado, la versión es la misma y no se duplica nada;
si ha cambiado (lote 2, el dato del domingo), queda registrado qué asientos cambiaron.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from upistas.dominio.versiones import diferencias, version_asientos
from upistas.puertos import AlmacenERP, ClienteERP, ErrorERP, Sincronizacion


def _ahora() -> datetime:
    return datetime.now().astimezone()  # con zona horaria: se guarda en UTC y se enseña en hora local


def sincronizar_erp(
    cliente: ClienteERP,
    almacen: AlmacenERP,
    ahora: Callable[[], datetime] = _ahora,
) -> Sincronizacion:
    inicio = ahora()
    try:
        descarga = cliente.descargar()
    except ErrorERP as exc:
        fallida = Sincronizacion(inicio=inicio, fin=ahora(), ok=False, error=str(exc))
        almacen.registrar(fallida, None)
        return fallida

    version = version_asientos(descarga.asientos)
    anterior = almacen.ultima()
    cambios = None
    if anterior and anterior.version != version:
        cambios = diferencias(almacen.asientos(anterior.version), descarga.asientos)

    sincronizacion = Sincronizacion(
        inicio=inicio,
        fin=ahora(),
        ok=True,
        version=version,
        n_asientos=len(descarga.asientos),
        lote2_cargado=descarga.lote2_cargado,
        estadisticas=descarga.estadisticas,
        nuevos=len(cambios.nuevos) if cambios else 0,
        modificados=len({c.asiento for c in cambios.modificados}) if cambios else 0,
        eliminados=len(cambios.eliminados) if cambios else 0,
    )
    es_nueva = anterior is None or anterior.version != version
    almacen.registrar(sincronizacion, descarga.asientos if es_nueva else None)
    return sincronizacion
