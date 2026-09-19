import json
from decimal import Decimal
from pathlib import Path

from upistas.dominio.importes import parse_fecha
from upistas.dominio.modelos import Asiento


class ErpSnapshot:
    def __init__(self, ruta: Path):
        self.ruta = ruta

    def asientos(self) -> list[Asiento]:
        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, list):
            raise ValueError("El snapshot del ERP debe ser una lista de asientos")
        resultado = {}
        for fila in datos:
            fecha = parse_fecha(fila["fecha"])
            importe = Decimal(str(fila["importe"]))
            pedido = fila["pedido"].strip().upper()
            estado = fila["estado"].strip().upper()
            if fecha is None or not importe.is_finite() or estado not in {"PAGADA", "PENDIENTE"}:
                raise ValueError(f"Asiento inválido: {fila['id']}")
            if pedido in resultado:
                raise ValueError(f"Pedido repetido en snapshot ERP: {pedido}")
            resultado[pedido] = Asiento(fila["id"], pedido, fila["proveedor_id"], fila.get("nif", "").strip().upper(), importe, fecha, estado)
        return list(resultado.values())
