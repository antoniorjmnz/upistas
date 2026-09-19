"""Raíz de composición: el único sitio que decide qué adaptador implementa cada puerto.

Cambiar de Excel a otra fuente, añadir un lector de emails o cambiar de proveedor de LLM
se hace aquí (o en .env), sin tocar dominio ni aplicación.
"""
from __future__ import annotations

from datetime import date
from functools import cache

from upistas.adaptadores.fuentes.erp_copia import ErpDesdeCopia
from upistas.adaptadores.fuentes.erp_http import ClienteErpHttp
from upistas.adaptadores.fuentes.memoria import MaestroEnMemoria
from upistas.adaptadores.lectores.pdf import InspectorPdf
from upistas.adaptadores.lectores.pdf_texto import LectorPdfTexto
from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.config import ROOT, settings
from upistas.dominio.modelos import Referencias
from upistas.dominio.norma import Norma
from upistas.infra import django_setup
from upistas.puertos import AlmacenERP, ClienteERP, FuenteERP, FuenteMaestro, Inspector, LectorDocumento


@cache
def inspector() -> Inspector:
    return InspectorPdf()


@cache
def lectores() -> tuple[LectorDocumento, ...]:
    # Del más barato al más caro: texto determinista → LLM texto → LLM visión.
    return (LectorPdfTexto(),)


@cache
def maestro() -> FuenteMaestro:
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
    return ErpDesdeCopia(almacen_erp())


@cache
def norma(version: str) -> Norma:
    return Norma.desde_toml(ROOT / "normas" / f"{version}.toml")


@cache
def referencias() -> Referencias:
    return Referencias(
        proveedores={p.nif: p for p in maestro().proveedores()},
        pedidos={p.id: p for p in maestro().pedidos()},
        asientos={a.pedido: a for a in erp().asientos()},
        hoy=settings.hoy or date.today(),
    )
