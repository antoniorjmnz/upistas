"""Raíz de composición: el único sitio que decide qué adaptador implementa cada puerto.

Cambiar de Excel a otra fuente, añadir un lector de emails o cambiar de proveedor de LLM
se hace aquí (o en .env), sin tocar dominio ni aplicación.
"""
from __future__ import annotations

from functools import cache

from upistas.adaptadores.fuentes.erp_copia import ErpDesdeCopia
from upistas.adaptadores.fuentes.erp_http import ClienteErpHttp
from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.adaptadores.fuentes.memoria import MaestroEnMemoria
from upistas.adaptadores.lectores.pdf import InspectorPdf
from upistas.adaptadores.lectores.pdf_texto import LectorPdfTexto
from upistas.adaptadores.persistencia.django_decisiones import RepositorioDecisionesDjango
from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.adaptadores.persistencia.django_lecturas import RepositorioLecturasDjango
from upistas.config import ROOT, settings
from upistas.dominio.norma import Norma
from upistas.infra import django_setup
from upistas.puertos import (
    AlmacenERP, ClienteERP, FuenteERP, FuenteMaestro, Inspector, LectorDocumento, RepositorioDecisiones, RepositorioLecturas,
)


@cache
def inspector() -> Inspector:
    return InspectorPdf()


@cache
def lectores() -> tuple[LectorDocumento, ...]:
    # Del más barato al más caro: texto determinista → LLM texto → LLM visión.
    return (LectorPdfTexto(),)


@cache
def maestro() -> FuenteMaestro:
    ruta = settings.caja_dir / "FINAL_v7_DEFINITIVO_ahorasi.xlsx"
    return MaestroExcel(ruta) if ruta.exists() else MaestroEnMemoria()


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
    return ErpDesdeCopia(almacen_erp())


@cache
def lecturas() -> RepositorioLecturas:
    django_setup.configurar()
    return RepositorioLecturasDjango()


@cache
def decisiones() -> RepositorioDecisiones:
    django_setup.configurar()
    return RepositorioDecisionesDjango()


@cache
def norma(version: str) -> Norma:
    return Norma.desde_toml(ROOT / "normas" / f"{version}.toml")
