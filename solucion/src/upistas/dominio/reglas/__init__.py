"""Registro de reglas de pago.

Añadir una regla:
  1. Crear un módulo en este paquete con una función `(factura, refs, params) -> Comprobacion`.
  2. Decorarla con `@regla("RX_nombre")`.
  3. Activarla en el fichero de norma (`normas/vN.toml`).
Ninguna otra parte del código cambia.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any

from upistas.dominio.modelos import Comprobacion, Factura, Referencias

FuncionRegla = Callable[[Factura, Referencias, Mapping[str, Any]], Comprobacion]

_REGISTRO: dict[str, FuncionRegla] = {}


def regla(nombre: str) -> Callable[[FuncionRegla], FuncionRegla]:
    def registrar(fn: FuncionRegla) -> FuncionRegla:
        if nombre in _REGISTRO:
            raise ValueError(f"Regla duplicada: {nombre}")
        _REGISTRO[nombre] = fn
        return fn

    return registrar


def obtener(nombre: str) -> FuncionRegla:
    _cargar_modulos()
    try:
        return _REGISTRO[nombre]
    except KeyError:
        raise KeyError(f"La norma pide la regla {nombre!r}, que no existe en dominio/reglas/") from None


def disponibles() -> list[str]:
    _cargar_modulos()
    return sorted(_REGISTRO)


@cache
def _cargar_modulos() -> None:
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
