from decimal import Decimal, ROUND_HALF_UP

from upistas.dominio.modelos import Comprobacion
from upistas.dominio.reglas import regla


def tolerancia(params):
    return Decimal(str(params.get("tolerancia", "0.01")))


@regla("R1_nif_iban")
def nif_iban(factura, refs, params):
    """NIF fuera del maestro o IBAN distinto: incumplimiento seguro. Si es el maestro el que no permite
    contrastar (ficha sin NIF o sin IBAN), no se da por probado: lo escala R6_proveedor_referencias."""
    proveedor = refs.proveedores.get(factura.nif)
    if proveedor is None:
        pedido = refs.asientos.get(factura.pedido) or refs.pedidos.get(factura.pedido)
        del_pedido = refs.proveedores_por_id.get(pedido.proveedor_id) if pedido else None
        if del_pedido is not None and not del_pedido.nif:
            return Comprobacion("R1_nif_iban", True, "El maestro no tiene NIF del proveedor del pedido: no se contrasta aquí")
        return Comprobacion("R1_nif_iban", False, "NIF no leído o no encontrado en el maestro")
    if not proveedor.iban:
        return Comprobacion("R1_nif_iban", True, "El maestro no tiene IBAN del proveedor: no se contrasta aquí")
    if not factura.iban or factura.iban != proveedor.iban:
        return Comprobacion("R1_nif_iban", False, "IBAN ausente o distinto del maestro")
    return Comprobacion("R1_nif_iban", True)


@regla("R2_pedido_importe")
def pedido_importe(factura, refs, params):
    """Pedido inexistente o importe distinto: incumplimiento seguro. Que el pedido sea de otro
    proveedor es una contradicción entre fuentes y la escala R6_proveedor_referencias."""
    pedido = refs.asiento(factura.pedido) or refs.pedidos.get(factura.pedido)
    if pedido is None:
        return Comprobacion("R2_pedido_importe", False, "Pedido ausente o no encontrado")
    if factura.total is None or abs(factura.total - pedido.importe) > tolerancia(params):
        return Comprobacion("R2_pedido_importe", False, f"Total {factura.total} distinto del pedido {pedido.importe}")
    return Comprobacion("R2_pedido_importe", True)


@regla("R3_datos_fiscales")
def datos_fiscales(factura, refs, params):
    valores = (factura.base, factura.iva_pct, factura.iva, factura.total)
    if any(v is None for v in valores):
        return Comprobacion("R3_datos_fiscales", False, "Faltan datos legibles para verificar el cálculo del IVA")
    if any(v < 0 for v in valores):
        return Comprobacion("R3_datos_fiscales", False, "Importes negativos: requieren revisión antes de aplicar la regla de IVA")
    return Comprobacion("R3_datos_fiscales", True)


@regla("R3_iva_total")
def iva_total(factura, refs, params):
    base, iva, total = factura.base, factura.iva, factura.total
    if None in (base, iva, total) or min(base, iva, total) < 0:
        return Comprobacion("R3_iva_total", True)
    tipos = [factura.iva_pct] if factura.iva_pct is not None else params.get("tipos_iva", [21, 10, 4])
    esperados = [(base * Decimal(str(tipo)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for tipo in tipos]
    if not any(abs(iva - esperado) <= tolerancia(params) for esperado in esperados):
        return Comprobacion("R3_iva_total", False, "La cuota de IVA no corresponde a la base y al tipo")
    if abs(total - base - iva) > tolerancia(params):
        return Comprobacion("R3_iva_total", False, "El total no coincide con base más IVA")
    return Comprobacion("R3_iva_total", True)


@regla("R5_erp_pendiente")
def erp_pendiente(factura, refs, params):
    if refs.erp_contradictorio(factura.pedido):
        cuantos = "dos" if len(refs.asientos[factura.pedido]) == 2 else "varios"
        return Comprobacion("R5_erp_pendiente", False, f"El ERP tiene {cuantos} apuntes que no cuadran para este pedido")
    asiento = refs.asiento(factura.pedido)
    if asiento is None:
        return Comprobacion("R5_erp_pendiente", False, "No hay asiento del ERP para comprobar el estado del pedido")
    if factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_erp_pendiente", False, "Pedido ya aprobado en otra decisión")
    if asiento.estado != "PENDIENTE":
        return Comprobacion("R5_erp_pendiente", False, f"Estado del ERP: {asiento.estado}")
    return Comprobacion("R5_erp_pendiente", True)


@regla("R5_no_pagada")
def no_pagada(factura, refs, params):
    asiento = refs.asiento(factura.pedido)
    if asiento is not None and asiento.estado == "PAGADA":
        return Comprobacion("R5_no_pagada", False, "Pedido ya pagado en el ERP")
    if factura.pedido and factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_no_pagada", False, "Pedido ya aprobado en otro lote")
    return Comprobacion("R5_no_pagada", True)
