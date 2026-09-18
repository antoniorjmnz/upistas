"""Raíz de composición: el único sitio que decide qué adaptador implementa cada puerto.

Cambiar de Excel a otra fuente, añadir un lector de emails o cambiar de proveedor de LLM
se hace aquí (o en .env), sin tocar dominio ni aplicación.
"""
from __future__ import annotations

from datetime import date
from functools import cache

from upistas.adaptadores.fuentes.memoria import ErpEnMemoria, MaestroEnMemoria
from upistas.adaptadores.lectores.pdf_texto import LectorPdfTexto
from upistas.config import ROOT, settings
from upistas.dominio.modelos import Referencias
from upistas.dominio.norma import Norma
from upistas.puertos import FuenteERP, FuenteMaestro, LectorDocumento


@cache
def lectores() -> tuple[LectorDocumento, ...]:
    # Del más barato al más caro: texto determinista → LLM texto → LLM visión.
    return (LectorPdfTexto(),)


@cache
def maestro() -> FuenteMaestro:
    return MaestroEnMemoria()  # Pendiente: adaptador del Excel de Alberto


@cache
def erp() -> FuenteERP:
    return ErpEnMemoria()  # Pendiente: adaptador del bridge HTTP del ERP


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
