from decimal import Decimal, ROUND_HALF_UP

from upistas.dominio.modelos import Comprobacion
from upistas.dominio.reglas import regla


def tolerancia(params):
    return Decimal(str(params.get("tolerancia", "0.01")))


@regla("R1_nif_iban")
def nif_iban(factura, refs, params):
    proveedor = refs.proveedores.get(factura.nif)
    if proveedor is None:
        return Comprobacion("R1_nif_iban", False, "NIF no leído o no encontrado en el maestro")
    if not factura.iban or not proveedor.iban or factura.iban != proveedor.iban:
        return Comprobacion("R1_nif_iban", False, "IBAN ausente o distinto del maestro")
    return Comprobacion("R1_nif_iban", True)


@regla("R2_pedido_importe")
def pedido_importe(factura, refs, params):
    pedido = refs.asientos.get(factura.pedido) or refs.pedidos.get(factura.pedido)
    proveedor = refs.proveedores.get(factura.nif)
    if pedido is None:
        return Comprobacion("R2_pedido_importe", False, "Pedido ausente o no encontrado")
    if proveedor is None or pedido.proveedor_id != proveedor.id or (pedido.nif and pedido.nif != factura.nif):
        return Comprobacion("R2_pedido_importe", False, "El pedido no pertenece al proveedor de la factura")
    if factura.total is None or abs(factura.total - pedido.importe) > tolerancia(params):
        return Comprobacion("R2_pedido_importe", False, f"Total {factura.total} distinto del pedido {pedido.importe}")
    return Comprobacion("R2_pedido_importe", True)


@regla("R3_iva_total")
def iva_total(factura, refs, params):
    base, iva, total = factura.base, factura.iva, factura.total
    if None in (base, iva, total):
        return Comprobacion("R3_iva_total", False, "Base, IVA o total ilegibles")
    if min(base, iva, total) < 0:
        return Comprobacion("R3_iva_total", False, "Importe negativo: requiere revisión")
    tipos = [factura.iva_pct] if factura.iva_pct is not None else params.get("tipos_iva", [21, 10, 4])
    esperados = [(base * Decimal(str(tipo)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for tipo in tipos]
    if not any(abs(iva - esperado) <= tolerancia(params) for esperado in esperados):
        return Comprobacion("R3_iva_total", False, "La cuota de IVA no corresponde a la base y al tipo")
    if abs(total - base - iva) > tolerancia(params):
        return Comprobacion("R3_iva_total", False, "El total no coincide con base más IVA")
    return Comprobacion("R3_iva_total", True)


@regla("R5_erp_pendiente")
def erp_pendiente(factura, refs, params):
    asiento = refs.asientos.get(factura.pedido)
    if asiento is None:
        return Comprobacion("R5_erp_pendiente", False, "No hay asiento del ERP para comprobar el estado del pedido")
    if factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_erp_pendiente", False, "Pedido ya aprobado en otra decisión")
    if asiento.estado != "PENDIENTE":
        return Comprobacion("R5_erp_pendiente", False, f"Estado del ERP: {asiento.estado}")
    return Comprobacion("R5_erp_pendiente", True)


@regla("R5_no_pagada")
def no_pagada(factura, refs, params):
    asiento = refs.asientos.get(factura.pedido)
    if asiento is not None and asiento.estado == "PAGADA":
        return Comprobacion("R5_no_pagada", False, "Pedido ya pagado en el ERP")
    if factura.pedido and factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_no_pagada", False, "Pedido ya aprobado en otro lote")
    return Comprobacion("R5_no_pagada", True)
