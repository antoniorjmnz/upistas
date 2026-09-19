"""Filas con cabecera → Proveedor y Pedido del dominio.

Lo comparten el Excel de Alberto (`excel.py`) y los CSV de altas (`csv_altas.py`): la misma limpieza de
cabeceras, NIF, IBAN, importes y fechas, venga la fila de una hoja o de un fichero de texto.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from upistas.dominio.importes import normaliza_iban, parse_fecha, parse_importe
from upistas.dominio.modelos import Pedido, Proveedor

PATRON_PEDIDO = re.compile(r"^PO-\d{4}-\d{4}$")
PATRON_NIF = re.compile(r"^[A-Z]\d{7}[A-Z0-9]$")
PATRON_NIF_EXTRANJERO = re.compile(r"^[A-Z0-9./-]{8,20}$")  # tal como viene en la factura: DE812345678, 12.345.678/0001-95


def nif_valido(nif: str) -> bool:
    """Un NIF español con su formato, o uno extranjero tal cual (lo mismo que admite el formulario)."""
    return bool(PATRON_NIF.match(nif) or PATRON_NIF_EXTRANJERO.match(nif))

CABECERAS_PROVEEDOR = {"id", "razonsocial", "nif", "iban"}
CABECERAS_PEDIDO = {"pedido", "importe"}

Fila = dict[str, object]


def cabecera(valor) -> str:
    """`Razon Social`, `ProveedorID` y `proveedor_id` se buscan igual: minúsculas, sin espacios ni guiones bajos."""
    return re.sub(r"[\s_]+", "", str(valor)).lower() if valor is not None else ""


def es_cabecera(nombres: list[str], obligatorias: set[str]) -> bool:
    return any(o in nombres or any(n.startswith(o) for n in nombres) for o in obligatorias)


def proveedor_de_fila(fila: Fila) -> Proveedor:
    """La fila tal cual, limpia: el NIF en mayúsculas, el IBAN sin espacios, los días como número."""
    return Proveedor(
        id=texto(fila.get("id")).upper(),
        nombre=texto(fila.get("razonsocial")),
        nif=texto(fila.get("nif")).replace(" ", "").upper(),
        iban=normaliza_iban(texto(fila.get("iban"))) or "",
        ciudad=texto(fila.get("ciudad")),
        condiciones_dias=dias(fila.get("condiciones")),
    )


def importe_de_fila(fila: Fila) -> Decimal | None:
    return decimal(fila.get("importe") if "importe" in fila else fila.get("importetotal"))


def pedido_de_fila(fila: Fila, importe: Decimal, estado_por_defecto: str) -> Pedido:
    return Pedido(
        id=texto(fila.get("pedido")).upper(),
        proveedor_id=texto(fila.get("proveedorid")).upper(),
        nif=texto(fila.get("nif")).replace(" ", "").upper(),
        importe=importe,
        estado=texto(fila.get("estado")).upper() or estado_por_defecto,
        fecha=fecha(fila.get("fechapedido")),
    )


def leer_proveedores(filas: Iterable[Fila], avisos: list[str]) -> list[Proveedor]:
    vistos: dict[str, Proveedor] = {}
    por_nif: dict[str, Proveedor] = {}
    for fila in filas:
        p = proveedor_de_fila(fila)
        pid = p.id
        if not pid:
            continue
        anterior = vistos.get(pid) or por_nif.get(p.nif)
        if anterior and (anterior.id, anterior.nif, anterior.iban) != (p.id, p.nif, p.iban):
            raise ValueError(f"Maestro contradictorio: proveedor {pid}")
        if pid in vistos:
            if vistos[pid] != p:
                avisos.append(f"Proveedor {pid} repetido con datos distintos; se usa el primero")
            else:
                avisos.append(f"Proveedor {pid} repetido")
            continue
        if not PATRON_NIF.match(p.nif):
            avisos.append(f"Proveedor {pid} con NIF raro: {p.nif!r}")
        vistos[pid] = p
        if p.nif:
            por_nif[p.nif] = p
    return list(vistos.values())


def leer_pedidos(filas: Iterable[Fila], avisos: list[str], estado_por_defecto: str, origen: str) -> list[Pedido]:
    pedidos: list[Pedido] = []
    vistos: set[str] = set()
    for fila in filas:
        pid = texto(fila.get("pedido")).upper()
        if not PATRON_PEDIDO.match(pid):
            continue
        if pid in vistos:
            avisos.append(f"Pedido {pid} repetido en {origen}")
            continue
        importe = importe_de_fila(fila)
        if importe is None:
            avisos.append(f"Pedido {pid} sin importe legible")
            continue
        vistos.add(pid)
        pedidos.append(pedido_de_fila(fila, importe, estado_por_defecto))
    return pedidos


def texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def decimal(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        importe = Decimal(str(valor))
    except InvalidOperation:
        importe = parse_importe(str(valor))
    return importe if importe is not None and importe.is_finite() else None


def fecha(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return parse_fecha(texto(valor))


def dias(valor) -> int | None:
    m = re.search(r"\d+", texto(valor))
    return int(m.group(0)) if m else None
