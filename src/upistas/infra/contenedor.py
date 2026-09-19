"""Raíz de composición: el único sitio que decide qué adaptador implementa cada puerto.

Cambiar de Excel a otra fuente, añadir un lector de emails o cambiar de proveedor de LLM
se hace aquí (o en .env), sin tocar dominio ni aplicación.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from functools import cache
from pathlib import Path

from upistas.adaptadores.fuentes.erp_copia import ErpDesdeCopia
from upistas.adaptadores.fuentes.erp_http import ClienteErpHttp
from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.adaptadores.fuentes.memoria import MaestroEnMemoria
from upistas.adaptadores.fuentes.snapshot import ErpSnapshot
from upistas.adaptadores.lectores.fal_ocr import FalOCR
from upistas.adaptadores.lectores.pdf_unificado import VERSION, LectorPdfUnificado
from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.config import ROOT, Settings, settings
from upistas.dominio.modelos import Referencias
from upistas.dominio.norma import Norma
from upistas.dominio.versiones import version_asientos
from upistas.infra import django_setup
from upistas.puertos import AlmacenERP, ClienteERP, FuenteERP, FuenteMaestro


@cache
def lectores() -> tuple[LectorPdfUnificado, ...]:
    # Del más barato al más caro: texto determinista → LLM texto → LLM visión.
    return (LectorPdfUnificado(
        ocr=FalOCR() if settings.usar_ocr else None,
        cache_dir=settings.outputs_dir / "extracciones",
    ),)


def texto_extraido(ruta: Path) -> str:
    return lectores()[0].texto_extraido(ruta)


def rutas_maestro() -> tuple[Path, ...]:
    nombre = "FINAL_v7_DEFINITIVO_ahorasi.xlsx"
    return tuple(carpeta / nombre for carpeta in (
        settings.caja_dir, ROOT / "data", ROOT / "src", ROOT / "src" / "upistas", ROOT,
    ))


@cache
def maestro() -> FuenteMaestro:
    if settings.excel_path is not None:
        return MaestroExcel(settings.excel_path)
    candidatas = list(dict.fromkeys(r.resolve() for r in rutas_maestro() if r.is_file()))
    if len(candidatas) > 1:
        raise ValueError("Hay varios maestros Excel; indica cuál usar mediante --excel o EXCEL_PATH")
    if candidatas:
        return MaestroExcel(candidatas[0])
    return MaestroEnMemoria()  # Pendiente: adaptador del Excel de Alberto (#25)


@cache
def cliente_erp() -> ClienteERP:
    """El bridge de 2009 en vivo. Solo lo usa la sincronización."""
    return ClienteErpHttp(settings.erp_url, settings.erp_user, settings.erp_password)


@cache
def almacen_erp() -> AlmacenERP:
    django_setup.configurar()
    return AlmacenERPDjango()


@cache
def erp() -> FuenteERP:
    """Con lo que deciden las reglas: la copia local, nunca el bridge en vivo."""
    if settings.erp_snapshot is not None:
        return ErpSnapshot(settings.erp_snapshot)
    return ErpDesdeCopia(almacen_erp())


@cache
def norma(version: str) -> Norma:
    return Norma.desde_toml(ROOT / "normas" / f"{version}.toml")


@cache
def referencias() -> Referencias:
    fuente = maestro()
    asientos = erp().asientos()
    if len({a.pedido for a in asientos}) != len(asientos):
        raise ValueError("ERP: hay varios asientos para un mismo pedido; requiere revisión")
    return Referencias(
        proveedores={p.nif: p for p in fuente.proveedores()},
        pedidos={p.id: p for p in fuente.pedidos()},
        asientos={a.pedido: a for a in asientos},
        hoy=settings.hoy or date.today(),
        marcados_por_alberto=fuente.marcados_para_revisar() if isinstance(fuente, MaestroExcel) else frozenset(),
        version_datos=f"{getattr(fuente, 'version', '')}:{version_asientos(asientos)}",
    )


def configurar(nuevos: Settings) -> None:
    global settings
    settings = nuevos
    for funcion in (lectores, maestro, erp, cliente_erp, almacen_erp, norma, referencias):
        funcion.cache_clear()


def huella(version: str) -> str:
    codigo = hashlib.sha256()
    for ruta in sorted((ROOT / "src" / "upistas").rglob("*.py")):
        codigo.update(ruta.relative_to(ROOT).as_posix().encode() + b"\0" + ruta.read_bytes() + b"\0")
    contenido = json.dumps({
        "codigo": codigo.hexdigest(),
        "referencias": asdict(referencias()),
        "norma": asdict(norma(version)),
        "extractor": VERSION,
        "ocr": settings.usar_ocr,
    }, sort_keys=True, default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else str(v))
    return hashlib.sha256(contenido.encode()).hexdigest()
