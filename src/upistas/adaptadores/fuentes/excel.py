"""El Excel de Alberto (`FINAL_v7_DEFINITIVO_ahorasi.xlsx`) como fuente de proveedores y pedidos.

Lo que hay dentro y cómo lo tratamos:
- `Proveedores`: 11 proveedores, con P007 repetido y espacios de más en algún nombre.
- `Pedidos_2026`: 516 pedidos. `Estado` dice ABIERTO en todos (no es fiable) y hay 20 sin NIF.
- `Pedidos_2025_OLD`: dos pedidos antiguos; se cargan marcados como archivados.
- `pendiente_revisar`: pedidos que el propio Alberto marcó a mano para mirar.
- `Norma_Pagos_v3`: el texto de la norma. Las demás hojas son basura y se ignoran.
Las hojas se buscan por nombre y las columnas por cabecera, no por posición.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from pathlib import Path

import openpyxl

from upistas.dominio.importes import normaliza_iban, parse_fecha
from upistas.dominio.modelos import Pedido, Proveedor

PATRON_PEDIDO = re.compile(r"^PO-\d{4}-\d{4}$")
PATRON_NIF = re.compile(r"^[A-Z]\d{7}[A-Z0-9]$")


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
        wb.close()
        return {"proveedores": proveedores, "pedidos": pedidos, "marcados": marcados, "norma": norma}

    def _leer_proveedores(self, ws) -> list[Proveedor]:
        if ws is None:
            self.avisos.append("No hay hoja Proveedores")
            return []
        vistos: dict[str, Proveedor] = {}
        for fila in self._filas(ws, {"id", "razon social", "nif", "iban"}):
            pid = _texto(fila.get("id"))
            if not pid:
                continue
            p = Proveedor(
                id=pid,
                nombre=_texto(fila.get("razon social")),
                nif=_texto(fila.get("nif")).upper(),
                iban=normaliza_iban(_texto(fila.get("iban"))) or "",
                ciudad=_texto(fila.get("ciudad")),
                condiciones_dias=_dias(fila.get("condiciones")),
            )
            if pid in vistos:
                if vistos[pid] != p:
                    self.avisos.append(f"Proveedor {pid} repetido con datos distintos; se usa el primero")
                else:
                    self.avisos.append(f"Proveedor {pid} repetido")
                continue
            if not PATRON_NIF.match(p.nif):
                self.avisos.append(f"Proveedor {pid} con NIF raro: {p.nif!r}")
            vistos[pid] = p
        return list(vistos.values())

    def _leer_pedidos(self, ws, estado_por_defecto: str) -> list[Pedido]:
        if ws is None:
            return []
        pedidos: list[Pedido] = []
        vistos: set[str] = set()
        for fila in self._filas(ws, {"pedido", "importe"}):
            pid = _texto(fila.get("pedido"))
            if not PATRON_PEDIDO.match(pid):
                continue
            if pid in vistos:
                self.avisos.append(f"Pedido {pid} repetido en el Excel")
                continue
            importe = _decimal(fila.get("importe") if "importe" in fila else fila.get("importe_total"))
            if importe is None:
                self.avisos.append(f"Pedido {pid} sin importe legible")
                continue
            vistos.add(pid)
            pedidos.append(
                Pedido(
                    id=pid,
                    proveedor_id=_texto(fila.get("proveedorid")),
                    nif=_texto(fila.get("nif")).upper(),
                    importe=importe,
                    estado=_texto(fila.get("estado")).upper() or estado_por_defecto,
                    fecha=_fecha(fila.get("fecha_pedido")),
                )
            )
        return pedidos

    @staticmethod
    def _filas(ws, obligatorias: set[str]):
        """Filas como dict {cabecera normalizada: valor}. La cabecera se busca en las 5 primeras filas."""
        iterador = ws.iter_rows(values_only=True)
        cabecera = None
        for _ in range(5):
            fila = next(iterador, None)
            if fila is None:
                return
            nombres = [_cabecera(c) for c in fila]
            if any(o in nombres or any(n.startswith(o) for n in nombres) for o in obligatorias):
                cabecera = nombres
                break
        if cabecera is None:
            return
        for fila in iterador:
            if fila is None or all(c is None for c in fila):
                continue
            yield {n: v for n, v in zip(cabecera, fila) if n}

    @staticmethod
    def _columna(ws) -> list[str]:
        if ws is None:
            return []
        return [_texto(f[0]) for f in ws.iter_rows(values_only=True) if f and f[0] is not None and _texto(f[0])]


def _cabecera(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip().lower().replace("_", "_") if valor is not None else ""


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _decimal(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _fecha(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return parse_fecha(_texto(valor))


def _dias(valor) -> int | None:
    m = re.search(r"\d+", _texto(valor))
    return int(m.group(0)) if m else None
