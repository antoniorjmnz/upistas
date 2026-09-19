"""El Excel de Alberto (`FINAL_v7_DEFINITIVO_ahorasi.xlsx`) como fuente de proveedores y pedidos.

Lo que hay dentro y cómo lo tratamos:
- `Proveedores`: 11 proveedores, con P007 repetido y espacios de más en algún nombre.
- `Pedidos_2026`: 516 pedidos. `Estado` dice ABIERTO en todos (no es fiable) y hay 20 sin NIF.
- `Pedidos_2025_OLD`: dos pedidos antiguos; se cargan marcados como archivados.
- `pendiente_revisar`: pedidos que el propio Alberto marcó a mano para mirar.
- `Norma_Pagos_v3`: el texto de la norma. Las demás hojas son basura y se ignoran.
Las hojas se buscan por nombre y las columnas por cabecera, no por posición. La limpieza de cada fila
(cabeceras, NIF, IBAN, importes, fechas) está en `filas.py`, compartida con los CSV de altas.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import openpyxl

from upistas.adaptadores.fuentes.filas import (
    CABECERAS_PEDIDO,
    CABECERAS_PROVEEDOR,
    PATRON_NIF,  # noqa: F401  (lo usa el formulario de proveedores de la web)
    PATRON_PEDIDO,
    cabecera,
    es_cabecera,
    leer_pedidos,
    leer_proveedores,
    texto,
)
from upistas.dominio.modelos import Pedido, Proveedor


@dataclass
class MaestroExcel:
    ruta: Path
    avisos: list[str] = field(default_factory=list)

    # --- puerto FuenteMaestro --------------------------------------------------------------

    def proveedores(self) -> list[Proveedor]:
        return list(self._datos["proveedores"])

    def pedidos(self) -> list[Pedido]:
        return list(self._datos["pedidos"])

    # --- extras del Excel de Alberto ----------------------------------------------------------

    def marcados_para_revisar(self) -> frozenset[str]:
        """Hoja `pendiente_revisar`: lo que Alberto apuntó a mano."""
        return self._datos["marcados"]

    def texto_norma(self) -> list[str]:
        return list(self._datos["norma"])

    @cached_property
    def version(self) -> str:
        """Huella del fichero: cambia si Alberto cambia cualquier celda."""
        return hashlib.sha256(Path(self.ruta).read_bytes()).hexdigest()[:12]

    # --- lectura --------------------------------------------------------------------------------

    @cached_property
    def _datos(self) -> dict:
        wb = openpyxl.load_workbook(self.ruta, read_only=True, data_only=True)
        try:
            hojas = {ws.title.strip().lower(): ws for ws in wb.worksheets}

            def hoja(nombre: str):
                return hojas.get(nombre.lower())

            proveedores = self._leer_proveedores(hoja("Proveedores"))
            pedidos = self._leer_pedidos(hoja("Pedidos_2026"), estado_por_defecto="ABIERTO")
            antiguos = self._leer_pedidos(hoja("Pedidos_2025_OLD"), estado_por_defecto="ARCHIVADO_2025")
            ids = {p.id for p in pedidos}
            pedidos += [p for p in antiguos if p.id not in ids]
            marcados = frozenset(
                v for v in self._columna(hoja("pendiente_revisar")) if PATRON_PEDIDO.match(v)
            )
            norma = [v for v in self._columna(hoja("Norma_Pagos_v3"))]
            return {"proveedores": proveedores, "pedidos": pedidos, "marcados": marcados, "norma": norma}
        finally:
            wb.close()

    def _leer_proveedores(self, ws) -> list[Proveedor]:
        if ws is None:
            self.avisos.append("No hay hoja Proveedores")
            return []
        return leer_proveedores(self._filas(ws, CABECERAS_PROVEEDOR), self.avisos)

    def _leer_pedidos(self, ws, estado_por_defecto: str) -> list[Pedido]:
        if ws is None:
            return []
        return leer_pedidos(self._filas(ws, CABECERAS_PEDIDO), self.avisos, estado_por_defecto, origen="el Excel")

    @staticmethod
    def _filas(ws, obligatorias: set[str]):
        """Filas como dict {cabecera normalizada: valor}. La cabecera se busca en las 5 primeras filas."""
        iterador = ws.iter_rows(values_only=True)
        nombres = None
        for _ in range(5):
            fila = next(iterador, None)
            if fila is None:
                return
            candidata = [cabecera(c) for c in fila]
            if es_cabecera(candidata, obligatorias):
                nombres = candidata
                break
        if nombres is None:
            return
        for fila in iterador:
            if fila is None or all(c is None for c in fila):
                continue
            yield {n: v for n, v in zip(nombres, fila) if n}

    @staticmethod
    def _columna(ws) -> list[str]:
        if ws is None:
            return []
        return [texto(f[0]) for f in ws.iter_rows(values_only=True) if f and f[0] is not None and texto(f[0])]
