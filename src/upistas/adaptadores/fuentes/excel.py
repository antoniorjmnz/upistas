from decimal import Decimal
from functools import cached_property
from pathlib import Path

from openpyxl import load_workbook

from upistas.dominio.importes import normaliza_iban, parse_importe
from upistas.dominio.modelos import Pedido, Proveedor


class MaestroExcel:
    def __init__(self, ruta: Path):
        self.ruta = ruta

    @cached_property
    def _hojas(self):
        libro = load_workbook(self.ruta, read_only=True, data_only=True)
        try:
            hojas = {}
            for nombre, columnas in (
                ("Proveedores", {"ID", "NIF", "IBAN"}),
                ("Pedidos_2026", {"Pedido", "ProveedorID", "Importe_Total"}),
            ):
                filas = iter(libro[nombre].iter_rows(values_only=True))
                cabecera = [str(c or "").strip() for c in next(filas)]
                if not columnas.issubset(cabecera):
                    raise ValueError(f"Faltan columnas en {nombre}: {sorted(columnas - set(cabecera))}")
                hojas[nombre] = [{
                    columna: valor if columna == "Importe_Total" and type(valor) in (int, float)
                    else str(valor).strip() if valor is not None else ""
                    for columna, valor in zip(cabecera, fila)
                } for fila in filas if any(v is not None for v in fila)]
            return hojas
        finally:
            libro.close()

    def proveedores(self) -> list[Proveedor]:
        resultado = {}
        for fila in self._hojas["Proveedores"]:
            nif = fila["NIF"].upper().replace(" ", "")
            proveedor = Proveedor(fila["ID"], fila.get("Razon Social", ""), nif, normaliza_iban(fila["IBAN"]) or "")
            anterior = resultado.get(nif)
            if not nif or (anterior is not None and (anterior.id, anterior.iban) != (proveedor.id, proveedor.iban)):
                raise ValueError(f"Maestro contradictorio o sin NIF: {fila['ID']}")
            resultado[nif] = proveedor
        return list(resultado.values())

    def pedidos(self) -> list[Pedido]:
        resultado = {}
        for fila in self._hojas["Pedidos_2026"]:
            codigo = fila["Pedido"].upper().replace(" ", "")
            valor = fila["Importe_Total"]
            importe = Decimal(str(valor)) if isinstance(valor, (int, float)) else parse_importe(valor)
            if not codigo or importe is None or not importe.is_finite():
                raise ValueError(f"Pedido o importe ilegible: {codigo}")
            pedido = Pedido(codigo, fila["ProveedorID"], fila.get("NIF", "").upper().replace(" ", ""), importe)
            if codigo in resultado and resultado[codigo] != pedido:
                raise ValueError(f"Pedido contradictorio: {codigo}")
            resultado[codigo] = pedido
        return list(resultado.values())
