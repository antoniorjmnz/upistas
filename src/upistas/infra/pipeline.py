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
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from dbos import DBOS, DBOSConfig, SetWorkflowID, WorkflowHandle

from upistas.aplicacion import lote as lote_app
from upistas.aplicacion.mapeo import a_factura
from upistas.aplicacion.referencias import construir_referencias
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.config import settings
from upistas.dominio.modelos import EvaluacionNotas, Referencias
from upistas.infra import contenedor, django_setup, lectura_acotada
from upistas.puertos import DecisionGuardada, Ejecucion, RegistroLectura, Sincronizacion

COLA = "lecturas"
VERSION_LECTURA = "1"  # súbelo cuando cambien los lectores y haya que volver a leer todo

_config: DBOSConfig = {"name": "upistas", "system_database_url": settings.dbos_url}
DBOS(config=_config)

_cerrojos = {}
_guardia_cerrojos = threading.Lock()
_fallos_lectura = {}


# --- Lectura duradera ------------------------------------------------------------------------


@DBOS.step()
def leer_y_guardar(lote: str, file_id: str, ruta: str) -> dict:
    try:
        return _leer_y_guardar(lote, file_id, ruta)
    finally:
        django_setup.cerrar_conexion()


def _leer_y_guardar(lote: str, file_id: str, ruta: str) -> dict:
    doc = lectura_acotada.identificar(Path(ruta))
    firma = contenedor.huella_lectores()
    clave = (firma, doc.sha256 or doc.ruta)
    with _guardia_cerrojos:
        cerrojo = _cerrojos.setdefault(clave, threading.Lock())
    with cerrojo:
        return _leer_identificado(lote, file_id, ruta, doc, firma, clave)


def _leer_identificado(lote, file_id, ruta, doc, firma, clave):
    t0 = time.perf_counter()
    repo = contenedor.lecturas()
    previa = repo.por_sha(doc.sha256) if doc.sha256 else None
    if previa is not None and previa.leida and not previa.extraida.errores and (previa.extraida.lector or "").endswith(f"@{firma}"):  # mismo contenido ya leído: se reutiliza
        registro = RegistroLectura(
            lote=lote, file_id=file_id, ruta=ruta, sha256=doc.sha256, bytes=doc.bytes, tipo=previa.tipo, paginas=previa.paginas,
            alertas=previa.alertas, extraida=previa.extraida.model_copy(update={"file_id": file_id}), intentos=previa.intentos,
            segundos=previa.segundos, tokens_in=previa.tokens_in, tokens_out=previa.tokens_out, coste_eur=previa.coste_eur, modelo=previa.modelo,
        )
        repo.guardar(registro)
        return {"file_id": file_id, "leida": True, "metodo": registro.metodo, "cache": True, "segundos": round(time.perf_counter() - t0, 3)}

    lectura = _fallos_lectura.get(clave) or lectura_acotada.leer(Path(ruta), contenedor.settings, doc)
    if lectura.extraida is None:
        _fallos_lectura[clave] = lectura
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


def encolar_lecturas(lote: str, rutas: Sequence[Path]) -> list[WorkflowHandle]:
    cola = DBOS.retrieve_queue(COLA)
    handles = []
    firma = contenedor.huella_lectores()
    fallidas = {r.file_id for r in contenedor.lecturas().del_lote(lote) if not r.leida or r.extraida.errores}
    reintento = uuid4().hex
    for ruta in rutas:
        identificado = lectura_acotada.identificar(ruta)
        contenido = identificado.sha256 or f"no_legible:{identificado.bytes}"
        identidad = hashlib.sha256(f"{ruta.resolve()}:{contenido}".encode()).hexdigest()
        sufijo = f":reintento:{reintento}" if ruta.name in fallidas else ""
        with SetWorkflowID(f"lectura:{VERSION_LECTURA}:{firma}:{lote}:{ruta.name}:{identidad}{sufijo}"):
            handles.append(cola.enqueue(leer_documento, lote, ruta.name, str(ruta)))
    return handles


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


def evaluar_notas(lecturas: Sequence[RegistroLectura], refs: Referencias) -> dict[str, EvaluacionNotas]:
    pendientes = [r for r in lecturas if r.extraida and not r.extraida.errores
                  and any(n.texto.strip() for n in (r.extraida.notas or []))]
    if not pendientes:
        return {}
    try:
        evaluador = contenedor.evaluador_notas()
    except Exception as exc:
        motivo = f"Evaluador de notas no disponible: {type(exc).__name__}"
        return {r.file_id: EvaluacionNotas(True, motivo, error=motivo) for r in pendientes}

    def valorar(registro):
        try:
            factura = a_factura(registro.extraida)
            factura = replace(factura, alertas=tuple(dict.fromkeys((*factura.alertas, *registro.alertas))))
            resultado = evaluador.evaluar(factura, refs)
        except Exception as exc:
            motivo = f"Fallo al evaluar notas: {type(exc).__name__}"
            resultado = EvaluacionNotas(True, motivo, error=motivo)
        return registro.file_id, resultado

    with ThreadPoolExecutor(max_workers=max(1, min(4, contenedor.settings.concurrencia))) as trabajadores:
        return dict(trabajadores.map(valorar, pendientes))


def procesar_lote(lote: str, rutas: Sequence[Path], version_norma: str, sincronizar: bool = True,
                  progreso: Callable[[int, int], None] | None = None) -> Informe:
    avisos: list[str] = []
    _fallos_lectura.clear()
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
    resultados = []
    handles = encolar_lecturas(lote, rutas)
    for numero, handle in enumerate(handles, 1):
        resultados.append(handle.get_result())
        if progreso:
            progreso(numero, len(handles))
    segundos_lectura = time.perf_counter() - t0
    nombres = {r.name for r in rutas}
    lecturas = [r for r in contenedor.lecturas().del_lote(lote) if r.file_id in nombres]
    if {r.file_id for r in lecturas} != nombres:
        raise RuntimeError("Faltan lecturas guardadas para completar el lote")

    t1 = time.perf_counter()
    refs = construir_referencias(
        maestro, contenedor.erp(), lecturas, contenedor.settings.hoy or date.today(),
        ultima.version or "", repo_dec.pedidos_aprobados(excepto_lote=lote),
        repo_dec.hashes_aprobados(excepto_lote=lote),
    )
    t_notas = time.perf_counter()
    evaluaciones = evaluar_notas(lecturas, refs)
    segundos_notas = time.perf_counter() - t_notas
    decisiones = lote_app.decidir_lote(lecturas, refs, contenedor.norma(version_norma), evaluaciones)
    repo_dec.guardar_decisiones(ejecucion.id, decisiones)
    segundos_decision = time.perf_counter() - t1 - segundos_notas

    anterior = next((e for e in repo_dec.ejecuciones(lote) if e.id != ejecucion.id and e.estado == "terminada"), None)
    cambios = lote_app.comparar(repo_dec.decisiones(anterior.id), decisiones) if anterior else []

    resumen = lote_app.resumen(decisiones, lecturas)
    resumen.update({
        "segundos_lectura": round(segundos_lectura, 2), "segundos_decision": round(segundos_decision, 2),
        "leidos_ahora": sum(1 for r in resultados if not r.get("cache")), "desde_cache": sum(1 for r in resultados if r.get("cache")),
        "cambios_respecto_anterior": len(cambios), "ejecucion_anterior": anterior.id if anterior else None,
        "segundos_notas": round(segundos_notas, 2),
        "notas_evaluadas": len(evaluaciones), "notas_desde_cache": sum(e.desde_cache for e in evaluaciones.values()),
        "notas_fallidas": sum(bool(e.error) for e in evaluaciones.values()),
        "tokens_notas_in": sum(e.tokens_in for e in evaluaciones.values()),
        "tokens_notas_out": sum(e.tokens_out for e in evaluaciones.values()),
    })
    ejecucion = repo_dec.terminar_ejecucion(ejecucion.id, resumen)
    return Informe(ejecucion, decisiones, lecturas, sinc, anterior, cambios, segundos_lectura, segundos_decision,
                   resumen["leidos_ahora"], resumen["desde_cache"], avisos)
