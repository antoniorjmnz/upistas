"""El pipeline: leer cada documento de forma duradera y decidir el lote.

Leer es lo caro (PDF, IA) y lo que puede fallar a mitad: cada documento es un workflow DBOS con
ID `lectura:{versión de lectores}:{lote}:{file_id}`. Si el proceso se cae, al arrancar DBOS retoma
los pendientes y no repite los terminados. Además, un contenido ya leído (misma huella sha256) no
se vuelve a leer aunque llegue con otro nombre o en otro lote.

Decidir es barato y determinista: se hace de golpe sobre todo el lote, con las referencias
montadas una vez (copia del ERP, Excel, memoria de pagos, índice del lote). Repetirlo no cuesta.
"""
from __future__ import annotations

import hashlib
import os
import platform
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dbos import DBOS, DBOSConfig, SetWorkflowID, WorkflowHandle

from upistas.aplicacion import lote as lote_app, procesar
from upistas.aplicacion.referencias import construir_referencias
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.config import settings
from upistas.infra import contenedor, django_setup
from upistas.puertos import DecisionGuardada, Ejecucion, RegistroLectura, Sincronizacion

COLA = "lecturas"
VERSION_LECTURA = "1"  # súbelo cuando cambien los lectores y haya que volver a leer todo

_config: DBOSConfig = {"name": "upistas", "system_database_url": settings.dbos_url}
DBOS(config=_config)


# --- Lectura duradera ------------------------------------------------------------------------


@DBOS.step()
def leer_y_guardar(lote: str, file_id: str, ruta: str) -> dict:
    try:
        return _leer_y_guardar(lote, file_id, ruta)
    finally:
        django_setup.cerrar_conexion()


def _leer_y_guardar(lote: str, file_id: str, ruta: str) -> dict:
    t0 = time.perf_counter()
    repo = contenedor.lecturas()
    doc = contenedor.inspector().inspeccionar(Path(ruta))
    firma = contenedor.huella_lectores()
    previa = repo.por_sha(doc.sha256) if doc.sha256 else None
    if previa is not None and previa.leida and (previa.extraida.lector or "").endswith(f"@{firma}"):  # mismo contenido ya leído: se reutiliza
        registro = RegistroLectura(
            lote=lote, file_id=file_id, ruta=ruta, sha256=doc.sha256, bytes=doc.bytes, tipo=doc.tipo, paginas=doc.paginas,
            alertas=doc.alertas, extraida=previa.extraida.model_copy(update={"file_id": file_id}), intentos=previa.intentos,
            segundos=previa.segundos, tokens_in=previa.tokens_in, tokens_out=previa.tokens_out, coste_eur=previa.coste_eur, modelo=previa.modelo,
        )
        repo.guardar(registro)
        return {"file_id": file_id, "leida": True, "metodo": registro.metodo, "cache": True, "segundos": round(time.perf_counter() - t0, 3)}

    lectura = procesar.leer_documento(Path(ruta), contenedor.inspector(), contenedor.lectores())
    extraida = lectura.extraida
    if extraida is not None:
        extraida = extraida.model_copy(update={"lector": f"{(extraida.lector or 'lector')[:15]}@{firma}"})
    coste = extraida.coste if extraida and extraida.coste else None
    registro = RegistroLectura(
        lote=lote, file_id=file_id, ruta=ruta, sha256=lectura.documento.sha256, bytes=lectura.documento.bytes,
        tipo=lectura.documento.tipo, paginas=lectura.documento.paginas, alertas=lectura.documento.alertas,
        extraida=extraida, intentos=lectura.intentos, segundos=round(time.perf_counter() - t0, 3),
        tokens_in=(coste.tokens_in or 0) if coste else 0, tokens_out=(coste.tokens_out or 0) if coste else 0,
        coste_eur=(coste.eur or 0.0) if coste else 0.0, modelo=(coste.modelo or "") if coste else "",
    )
    repo.guardar(registro)
    return {"file_id": file_id, "leida": registro.leida, "metodo": registro.metodo, "cache": False, "segundos": registro.segundos}


@DBOS.workflow()
def leer_documento(lote: str, file_id: str, ruta: str) -> dict:
    return leer_y_guardar(lote, file_id, ruta)


def iniciar() -> None:
    django_setup.configurar()
    DBOS.launch()
    DBOS.register_queue(COLA, global_concurrency=settings.concurrencia)


def _ya_leidos(lote: str, firma: str) -> dict[str, tuple[str, str]]:
    """Documentos del lote que ya tienen lectura buena con estos lectores: file_id → (sha256, método).

    Con eso, repasar un lote de 500 al que llegan 3 facturas nuevas solo pasa por DBOS esas 3;
    lo demás se decide con lo que ya está guardado.
    """
    ya: dict[str, tuple[str, str]] = {}
    for r in contenedor.lecturas().del_lote(lote):
        if r.leida and r.sha256 and (r.extraida.lector or "").endswith(f"@{firma}"):
            ya[r.file_id] = (r.sha256, r.metodo)
    return ya


def encolar_lecturas(lote: str, rutas: Sequence[Path]) -> tuple[list[WorkflowHandle], list[dict]]:
    """Encola la lectura de lo que no esté ya leído en este lote; lo que ya estaba vuelve como resultado de caché."""
    cola = DBOS.retrieve_queue(COLA)
    firma = contenedor.huella_lectores()
    ya = _ya_leidos(lote, firma)
    handles: list[WorkflowHandle] = []
    saltados: list[dict] = []
    for ruta in rutas:
        try:
            with ruta.open("rb") as fichero:
                contenido = hashlib.file_digest(fichero, "sha256").hexdigest()
        except OSError:
            contenido = "ausente"
        if ruta.name in ya and ya[ruta.name][0] == contenido:
            saltados.append({"file_id": ruta.name, "leida": True, "metodo": ya[ruta.name][1], "cache": True, "segundos": 0.0})
            continue
        identidad = hashlib.sha256(f"{ruta.resolve()}:{contenido}".encode()).hexdigest()
        with SetWorkflowID(f"lectura:{VERSION_LECTURA}:{firma}:{lote}:{ruta.name}:{identidad}"):
            handles.append(cola.enqueue(leer_documento, lote, ruta.name, str(ruta)))
    return handles, saltados


# --- Un lote de principio a fin ---------------------------------------------------------------


@dataclass
class Informe:
    ejecucion: Ejecucion
    decisiones: list[DecisionGuardada]
    lecturas: list[RegistroLectura]
    sincronizacion: Sincronizacion | None
    anterior: Ejecucion | None
    cambios: list[lote_app.Cambio]
    segundos_lectura: float
    segundos_decision: float
    leidos_ahora: int = 0
    desde_cache: int = 0
    avisos: list[str] = field(default_factory=list)


def hardware() -> dict:
    return {"sistema": platform.system(), "maquina": platform.machine(), "nucleos": os.cpu_count(), "python": platform.python_version()}


def procesar_lote(lote: str, rutas: Sequence[Path], version_norma: str, sincronizar: bool = True,
                  progreso: Callable[[int, int], None] | None = None) -> Informe:
    avisos: list[str] = []
    sinc = None
    if sincronizar or contenedor.settings.erp_snapshot is not None:
        sinc = sincronizar_erp(contenedor.cliente_erp(), contenedor.almacen_erp())
        if not sinc.ok:
            avisos.append(f"El ERP no respondió ({sinc.error}); se usa la última copia buena")
    ultima = contenedor.almacen_erp().ultima()
    if ultima is None:
        raise RuntimeError("No hay ninguna copia del ERP: arranca el ERP y ejecuta `upistas erp sync`")
    maestro = contenedor.maestro()
    repo_dec = contenedor.decisiones()

    ejecucion = repo_dec.iniciar_ejecucion(lote, version_norma, ultima.version or "", maestro.version, hardware())

    t0 = time.perf_counter()
    handles, resultados = encolar_lecturas(lote, rutas)
    if progreso and resultados:
        progreso(len(resultados), len(rutas))
    for numero, handle in enumerate(handles, len(resultados) + 1):
        resultados.append(handle.get_result())
        if progreso:
            progreso(numero, len(rutas))
    segundos_lectura = time.perf_counter() - t0
    nombres = {r.name for r in rutas}
    lecturas = [r for r in contenedor.lecturas().del_lote(lote) if r.file_id in nombres]
    if {r.file_id for r in lecturas} != nombres:
        raise RuntimeError("Faltan lecturas guardadas para completar el lote")

    t1 = time.perf_counter()
    refs = construir_referencias(
        maestro, contenedor.erp(), lecturas, contenedor.settings.hoy or date.today(),
        ultima.version or "", repo_dec.pedidos_aprobados(excepto_lote=lote),
    )
    decisiones = lote_app.decidir_lote(lecturas, refs, contenedor.norma(version_norma))
    repo_dec.guardar_decisiones(ejecucion.id, decisiones)
    segundos_decision = time.perf_counter() - t1

    anterior = next((e for e in repo_dec.ejecuciones(lote) if e.id != ejecucion.id and e.estado == "terminada"), None)
    cambios = lote_app.comparar(repo_dec.decisiones(anterior.id), decisiones) if anterior else []

    resumen = lote_app.resumen(decisiones, lecturas)
    resumen.update({
        "segundos_lectura": round(segundos_lectura, 2), "segundos_decision": round(segundos_decision, 2),
        "leidos_ahora": sum(1 for r in resultados if not r.get("cache")), "desde_cache": sum(1 for r in resultados if r.get("cache")),
        "cambios_respecto_anterior": len(cambios), "ejecucion_anterior": anterior.id if anterior else None,
    })
    ejecucion = repo_dec.terminar_ejecucion(ejecucion.id, resumen)
    return Informe(ejecucion, decisiones, lecturas, sinc, anterior, cambios, segundos_lectura, segundos_decision,
                   resumen["leidos_ahora"], resumen["desde_cache"], avisos)
