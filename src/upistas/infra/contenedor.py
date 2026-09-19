"""Raíz de composición: el único sitio que decide qué adaptador implementa cada puerto.

Cambiar de Excel a otra fuente, añadir un lector de emails o cambiar de proveedor de LLM
se hace aquí (o en .env), sin tocar dominio ni aplicación.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
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
from upistas.adaptadores.lectores.pdf import InspectorPdf
from upistas.adaptadores.lectores.pdf_unificado import VERSION, LectorPdfUnificado
from upistas.adaptadores.persistencia.django_decisiones import RepositorioDecisionesDjango
from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.adaptadores.persistencia.django_lecturas import RepositorioLecturasDjango
from upistas.adaptadores.persistencia.django_maestro import MaestroDjango
from upistas.config import ROOT, Settings, settings
from upistas.dominio.modelos import Referencias
from upistas.dominio.norma import Norma
from upistas.dominio.versiones import version_asientos
from upistas.infra import django_setup
from upistas.puertos import AlmacenERP, ClienteERP, EvaluadorNotas, FuenteERP, FuenteMaestro, Inspector, RepositorioDecisiones, RepositorioLecturas


@cache
def inspector() -> Inspector:
    return InspectorPdf()


def _ocr() -> Callable[[bytes], str] | None:
    """El proveedor de OCR para escaneados: fal (extra ocr) o firecrawl (httpx, sin extra)."""
    if not settings.usar_ocr:
        return None
    if settings.ocr_provider == "firecrawl":
        from upistas.adaptadores.lectores.firecrawl_ocr import FirecrawlOCR

        return FirecrawlOCR(settings.firecrawl_api_key, settings.firecrawl_base_url)
    return FalOCR()


@cache
def lectores() -> tuple[LectorPdfUnificado, ...]:
    # Del más barato al más caro: texto determinista → LLM texto → LLM visión.
    from upistas.adaptadores.lectores.vision_helmcode import VisionHelmcode

    vision = VisionHelmcode(
        settings.helmcode_api_key, settings.helmcode_base_url, settings.modelo_vision,
    ) if settings.usar_ocr and settings.helmcode_api_key else None
    return (LectorPdfUnificado(
        ocr=_ocr(),
        vision=vision,
        cache_dir=settings.outputs_dir / "extracciones",
    ),)


def texto_extraido(ruta: Path) -> str:
    return lectores()[0].texto_extraido(ruta)


def rutas_maestro() -> tuple[Path, ...]:
    nombre = "FINAL_v7_DEFINITIVO_ahorasi.xlsx"
    return tuple(carpeta / nombre for carpeta in (
        settings.caja_dir, ROOT / "data", ROOT / "src", ROOT / "src" / "upistas", ROOT,
    ))


def _maestro_propio() -> FuenteMaestro | None:
    """Nuestras tablas, si Alberto tiene proveedores dados de alta en la web (#38).

    Sin base de datos a mano (tests unitarios sin Django) no hay maestro propio y se sigue con el Excel.
    """
    from django.db import Error

    try:
        django_setup.configurar()
        return MaestroDjango() if MaestroDjango.hay_datos() else None
    except (Error, RuntimeError):
        return None


@cache
def maestro() -> FuenteMaestro:
    """Manda el Excel si lo piden a mano; si no, el maestro de la web; si tampoco, el Excel que se encuentre."""
    if settings.excel_path is not None:
        return MaestroExcel(settings.excel_path)
    propio = _maestro_propio()
    if propio is not None:
        return propio
    candidatas = list(dict.fromkeys(r.resolve() for r in rutas_maestro() if r.is_file()))
    if len(candidatas) > 1:
        raise ValueError("Hay varios maestros Excel; indica cuál usar mediante --excel o EXCEL_PATH")
    if candidatas:
        return MaestroExcel(candidatas[0])
    return MaestroEnMemoria()


@cache
def cliente_erp() -> ClienteERP:
    """El bridge de 2009 en vivo. Solo lo usa la sincronización."""
    if settings.erp_snapshot is not None:
        return ErpSnapshot(settings.erp_snapshot)
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
def lecturas() -> RepositorioLecturas:
    django_setup.configurar()
    return RepositorioLecturasDjango()


@cache
def decisiones() -> RepositorioDecisiones:
    django_setup.configurar()
    return RepositorioDecisionesDjango()


def evaluador_notas() -> EvaluadorNotas:
    from upistas.adaptadores.notas_helmcode import EvaluadorNotasHelmcode

    return EvaluadorNotasHelmcode(settings.helmcode_api_key, settings.helmcode_base_url, settings.modelo_notas,
                                 timeout=settings.notas_timeout_s, cache_dir=settings.outputs_dir / "notas",
                                 max_tokens=settings.notas_max_tokens)


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
        proveedores={p.nif: p for p in fuente.proveedores() if p.nif},
        proveedores_por_id={p.id: p for p in fuente.proveedores()},
        pedidos={p.id: p for p in fuente.pedidos()},
        asientos={a.pedido: a for a in asientos},
        hoy=settings.hoy or date.today(),
        marcados_por_alberto=fuente.marcados_para_revisar(),
        version_datos=f"{getattr(fuente, 'version', '')}:{version_asientos(asientos)}",
    )


def configurar(nuevos: Settings) -> None:
    global settings
    if not math.isfinite(nuevos.lectura_timeout_s) or nuevos.lectura_timeout_s <= 0:
        raise ValueError("LECTURA_TIMEOUT_S debe ser un número positivo y finito")
    if not math.isfinite(nuevos.notas_timeout_s) or nuevos.notas_timeout_s <= 0:
        raise ValueError("NOTAS_TIMEOUT_S debe ser un número positivo y finito")
    settings = nuevos
    for funcion in (inspector, lectores, maestro, erp, cliente_erp, almacen_erp, lecturas, decisiones, norma, referencias, huella_lectores):
        funcion.cache_clear()


@cache
def huella_lectores() -> str:
    codigo = hashlib.sha256(f"{VERSION}:{settings.usar_ocr}:{settings.ocr_provider}:{settings.lectura_timeout_s}".encode())
    base = ROOT / "src" / "upistas"
    rutas = list((base / "adaptadores" / "lectores").glob("*.py")) + [
        base / "dominio" / "notas.py", base / "dominio" / "importes.py",
        base / "contracts" / "factura_extraida.py", base / "puertos.py",
        base / "aplicacion" / "procesar.py", base / "infra" / "lectura_acotada.py",
    ]
    for ruta in sorted(rutas):
        codigo.update(ruta.relative_to(ROOT).as_posix().encode() + b"\0" + ruta.read_bytes() + b"\0")
    return codigo.hexdigest()[:24]


def huella(version: str) -> str:
    contenido = json.dumps({
        "codigo": huella_lectores(),
        "referencias": asdict(referencias()),
        "norma": asdict(norma(version)),
    }, sort_keys=True, default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else str(v))
    return hashlib.sha256(contenido.encode()).hexdigest()
