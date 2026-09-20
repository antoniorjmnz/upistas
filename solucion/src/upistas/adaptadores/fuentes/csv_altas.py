"""Los CSV de altas de La Caja (`proveedores_nuevos.csv`, `pedidos_nuevos.csv`) como fuente de proveedores y pedidos.

Traen las mismas columnas que el Excel de Alberto con las cabeceras escritas a su manera (`proveedor_id`
donde el Excel dice `ProveedorID`): `filas.py` las normaliza y hace la misma limpieza. Sirve como
FuenteMaestro por sí solo o como complemento del Excel en `importar_maestro`. No trae marcas de revisar:
eso Alberto lo hace en la web.
"""
from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from upistas.adaptadores.fuentes.filas import (
    CABECERAS_PEDIDO,
    CABECERAS_PROVEEDOR,
    Fila,
    cabecera,
    es_cabecera,
    leer_pedidos,
    leer_proveedores,
)
from upistas.dominio.modelos import Pedido, Proveedor

ILEGIBLE = "tiene caracteres que no se han podido leer"


@dataclass
class AltasCSV:
    rutas_proveedores: tuple[Path, ...] = ()
    rutas_pedidos: tuple[Path, ...] = ()
    avisos: list[str] = field(default_factory=list)

    # --- puerto FuenteMaestro --------------------------------------------------------------

    def proveedores(self) -> list[Proveedor]:
        return list(self._datos["proveedores"])

    def pedidos(self) -> list[Pedido]:
        return list(self._datos["pedidos"])

    def marcados_para_revisar(self) -> frozenset[str]:
        return frozenset()

    @cached_property
    def version(self) -> str:
        """Huella de todos los ficheros: cambia si cambia cualquiera."""
        huella = hashlib.sha256()
        for ruta in (*self.rutas_proveedores, *self.rutas_pedidos):
            huella.update(Path(ruta).read_bytes())
        return huella.hexdigest()[:12]

    # --- lectura --------------------------------------------------------------------------------

    @cached_property
    def _datos(self) -> dict:
        proveedores = leer_proveedores(self._filas(self.rutas_proveedores, CABECERAS_PROVEEDOR), self.avisos)
        pedidos = leer_pedidos(self._filas(self.rutas_pedidos, CABECERAS_PEDIDO), self.avisos, "ABIERTO", origen="los CSV")
        return {"proveedores": proveedores, "pedidos": pedidos}

    def _filas(self, rutas: Iterable[Path], obligatorias: set[str]) -> Iterator[Fila]:
        for ruta in rutas:
            yield from filas_csv(Path(ruta), obligatorias, self.avisos)


def filas_csv(ruta: Path, obligatorias: set[str], avisos: list[str]) -> Iterator[Fila]:
    """Filas del CSV como dict {cabecera normalizada: valor}. Coma o punto y coma, UTF-8 o Windows."""
    nombres, filas = tabla_csv(ruta.name, ruta.read_bytes(), avisos)
    if nombres and not es_cabecera(nombres, obligatorias):
        avisos.append(f"{ruta.name}: no tiene las columnas esperadas ({', '.join(sorted(obligatorias))})")
        return
    yield from filas


def tabla_csv(nombre: str, datos: bytes, avisos: list[str]) -> tuple[list[str], list[Fila]]:
    """Las cabeceras normalizadas y las filas con contenido de un CSV ya en memoria (subido por la web).
    Si el fichero trae bytes que no son de ninguna codificación conocida, se lee igual y se avisa."""
    lineas = _lineas(datos)
    if any("�" in linea for linea in lineas):
        avisos.append(f"{nombre}: {ILEGIBLE}")
    if not lineas:
        avisos.append(f"{nombre}: está vacío")
        return [], []
    separador = ";" if lineas[0].count(";") > lineas[0].count(",") else ","
    lector = csv.reader(lineas, delimiter=separador)
    nombres = [cabecera(c) for c in next(lector)]
    filas = [{n: v for n, v in zip(nombres, fila) if n} for fila in lector if any(c.strip() for c in fila)]
    return nombres, filas


def tipo_de_fichero(nombres: list[str]) -> str | None:
    """Por las cabeceras: «proveedores» (ID, Razon Social, NIF, IBAN…), «pedidos» (pedido, proveedor_id,
    importe_total…) o None si no es ni lo uno ni lo otro."""
    columnas = set(nombres)
    if CABECERAS_PROVEEDOR <= columnas:
        return "proveedores"
    if {"pedido", "proveedorid"} <= columnas and columnas & {"importe", "importetotal"}:
        return "pedidos"
    return None


def _lineas(datos: bytes) -> list[str]:
    try:
        texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = datos.decode("cp1252", errors="replace")
    return texto.splitlines()
