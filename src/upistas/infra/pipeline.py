"""Pipeline duradero: un workflow DBOS por documento.

Cada @DBOS.step queda guardado. Si el proceso se cae, al arrancar DBOS retoma cada documento
desde su último paso completado, sin repetir lecturas ni llamadas al LLM. El ID de workflow
`lote:norma:file_id` hace que reprocesar un lote no duplique nada; con otra norma, se crean
ejecuciones nuevas y ambas quedan trazadas.

Aquí no hay lógica de negocio: solo se orquestan los casos de uso de `aplicacion/`.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from dbos import DBOS, DBOSConfig, SetWorkflowID, WorkflowHandle

from upistas.aplicacion import procesar
from upistas.aplicacion.mapeo import a_outcome
from upistas.config import settings
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.infra import contenedor
from upistas.puertos import DocumentoInspeccionado

COLA = "documentos"

_config: DBOSConfig = {"name": "upistas", "system_database_url": settings.dbos_url}
DBOS(config=_config)


@DBOS.step()
def leer(ruta: str) -> dict:
    lectura = procesar.leer_documento(Path(ruta), contenedor.inspector(), contenedor.lectores())
    return {
        "documento": asdict(lectura.documento),
        "extraida": lectura.extraida.model_dump(mode="json") if lectura.extraida else None,
        "intentos": list(lectura.intentos),
    }


@DBOS.step()
def decidir(file_id: str, leido: dict, version_norma: str) -> dict:
    lectura = procesar.Lectura(
        documento=DocumentoInspeccionado(**leido["documento"]),
        extraida=FacturaExtraida.model_validate(leido["extraida"]) if leido["extraida"] else None,
        intentos=tuple(tuple(i) for i in leido["intentos"]),
    )
    norma = contenedor.norma(version_norma)
    refs = contenedor.referencias() if lectura.extraida else None
    return a_outcome(procesar.decidir(file_id, lectura, refs, norma), metodo=lectura.extraida.metodo.value if lectura.extraida else "ninguno")


@DBOS.workflow()
def procesar_documento(file_id: str, ruta: str, version_norma: str) -> dict:
    return decidir(file_id, leer(ruta), version_norma)


def iniciar() -> None:
    DBOS.launch()
    DBOS.register_queue(COLA, global_concurrency=settings.concurrencia)


def encolar_lote(rutas: list[Path], lote: str, version_norma: str) -> list[WorkflowHandle]:
    cola = DBOS.retrieve_queue(COLA)
    handles = []
    for ruta in rutas:
        with SetWorkflowID(f"{lote}:{version_norma}:{ruta.name}"):
            handles.append(cola.enqueue(procesar_documento, ruta.name, str(ruta), version_norma))
    return handles
