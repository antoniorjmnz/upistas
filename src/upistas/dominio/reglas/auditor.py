from decimal import Decimal, ROUND_HALF_UP

from upistas.dominio.divisas import TiposDeCambio, al_cambio, cuadra_al_cambio, importe_es, tipo_es
from upistas.dominio.importes import pais_del_nif
from upistas.dominio.modelos import Comprobacion
from upistas.dominio.reglas import regla


def tolerancia(params):
    return Decimal(str(params.get("tolerancia", "0.01")))


def en_otra_divisa(factura, nombre):
    """Con importes en otra moneda no se comparan con el pedido (en euros) ni se contrasta el IVA: lo dice R2_divisa."""
    return Comprobacion(nombre, True, f"No se compara: factura en {factura.divisa}") if factura.divisa != "EUR" else None


@regla("R1_nif_iban")
def nif_iban(factura, refs, params):
    """NIF fuera del maestro o IBAN distinto: incumplimiento seguro. Si es el maestro el que no permite
    contrastar (ficha sin NIF o sin IBAN), no se da por probado: lo escala R6_proveedor_referencias."""
    proveedor = refs.proveedores.get(factura.nif)
    if proveedor is None:
        pedido = refs.asiento(factura.pedido) or refs.pedidos.get(factura.pedido)
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
    """Pedido inexistente, de otro proveedor o con importe distinto: incumplimiento seguro (regla 2)."""
    pedido = refs.asiento(factura.pedido) or refs.pedidos.get(factura.pedido)
    proveedor = refs.proveedores.get(factura.nif)
    if pedido is None:
        return Comprobacion("R2_pedido_importe", False, "Pedido ausente o no encontrado")
    if factura.total is not None and factura.total < 0:
        return Comprobacion("R2_pedido_importe", True, "Importe negativo: lo revisa R3_datos_fiscales")
    if proveedor is None or pedido.proveedor_id != proveedor.id or (pedido.nif and pedido.nif != factura.nif):
        return Comprobacion("R2_pedido_importe", False, "El pedido no pertenece al proveedor de la factura")
    if otra := en_otra_divisa(factura, "R2_pedido_importe"):
        return otra
    if factura.total is None:
        if "total" not in factura.ausentes:  # no se pudo leer: lo dice R0_lectura y no se da por incumplido
            return Comprobacion("R2_pedido_importe", True, "No se compara: el total no se pudo leer")
        return Comprobacion("R2_pedido_importe", False, "La factura no trae total que comparar con el pedido")
    if abs(factura.total - pedido.importe) > tolerancia(params):
        return Comprobacion("R2_pedido_importe", False, f"Total {factura.total} distinto del pedido {pedido.importe}")
    return Comprobacion("R2_pedido_importe", True)


@regla("R2_divisa")
def divisa(factura, refs, params):
    """En otra moneda el total nunca se compara en bruto con el pedido (que va en euros) y la divisa por sí
    sola nunca es NO_PAGAR: se escala diciendo cuánto sale al tipo de referencia de normas/divisas.toml
    (que llega en params["divisas"]) y si cuadra. El pago en divisa lo autoriza Alberto."""
    nombre = "R2_divisa"
    if factura.divisa == "EUR":
        return Comprobacion(nombre, True)
    cambio = params.get("divisas") or TiposDeCambio()
    pedido = refs.asiento(factura.pedido) or refs.pedidos.get(factura.pedido)
    if factura.total is None:
        detalle = f"Factura en {factura.divisa}: el total no se pudo leer y no se compara con el pedido."
    elif pedido is None:
        detalle = f"Factura en {factura.divisa} ({importe_es(factura.total, factura.divisa)}): no hay pedido con el que comparar."
    else:
        detalle = f"Factura en {factura.divisa} ({importe_es(factura.total, factura.divisa)}); el pedido es de {importe_es(pedido.importe)}: "
        en_euros = al_cambio(factura.total, factura.divisa, cambio.tipos)
        if en_euros is None:
            detalle += f"no hay tipo de cambio de referencia para {factura.divisa}."
        else:
            detalle += f"al tipo de referencia (1 € = {tipo_es(cambio.tipos[factura.divisa])} {factura.divisa}) son {importe_es(en_euros)}, "
            if cuadra_al_cambio(en_euros, pedido.importe, cambio.tolerancia_pct):
                detalle += "cuadra con el pedido. El pago en divisa lo autoriza usted."
            else:
                detalle += f"no cuadra con el pedido ({importe_es(pedido.importe)})."
    if pais_del_nif(factura.nif) == "ES":
        detalle += f" Aviso: proveedor español facturando en {factura.divisa}."
    return Comprobacion(nombre, False, detalle)


@regla("R3_datos_fiscales")
def datos_fiscales(factura, refs, params):
    """Duda, no incumplimiento: sin importes legibles no se comprueba nada, y sin el tipo de IVA impreso
    no se contrasta la cuota. La suma base + IVA = total no necesita el tipo: la prueba R3_iva_total."""
    if otra := en_otra_divisa(factura, "R3_datos_fiscales"):
        return otra
    importes = (factura.base, factura.iva, factura.total)
    if any(v is None for v in importes):
        return Comprobacion("R3_datos_fiscales", False, "Faltan importes legibles para verificar el IVA y el total")
    if any(v < 0 for v in (*importes, factura.iva_pct) if v is not None):
        return Comprobacion("R3_datos_fiscales", False, "Importes negativos: requieren revisión antes de aplicar la regla de IVA")
    if factura.iva_pct is None:
        return Comprobacion("R3_datos_fiscales", False, "Sin el tipo de IVA impreso no se puede contrastar la cuota")
    # Un proveedor de fuera de España que cobra IVA español es una duda fiscal (inversión del sujeto pasivo o
    # exención): la mira una persona. El país sale del formato del NIF; si no se sabe, no se supone nada.
    pais = pais_del_nif(factura.nif)
    if pais not in ("ES", "??") and factura.iva_pct in (21, 10, 4) and factura.iva > 0:
        return Comprobacion("R3_datos_fiscales", False,
                            f"Proveedor de fuera de España ({pais}) cobra IVA español ({factura.iva_pct:g} %): comprobar inversión del sujeto pasivo")
    return Comprobacion("R3_datos_fiscales", True)


@regla("R3_iva_total")
def iva_total(factura, refs, params):
    """Incumplimiento seguro con importes legibles: la cuota se contrasta solo con el tipo impreso;
    la suma se comprueba siempre, con o sin tipo."""
    if otra := en_otra_divisa(factura, "R3_iva_total"):
        return otra
    base, iva, total = factura.base, factura.iva, factura.total
    if None in (base, iva, total) or min(base, iva, total) < 0:
        return Comprobacion("R3_iva_total", True)
    if factura.iva_pct is not None:
        esperado = (base * Decimal(str(factura.iva_pct)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(iva - esperado) > tolerancia(params):
            return Comprobacion("R3_iva_total", False, "La cuota de IVA no corresponde a la base y al tipo")
    if abs(total - base - iva) > tolerancia(params):
        return Comprobacion("R3_iva_total", False, "El total no coincide con base más IVA")
    return Comprobacion("R3_iva_total", True)


YA_APROBADO = "Pedido ya aprobado para pago en otro lote"


def ya_pagado(asiento):
    """«Pedido ya pagado en el ERP (asiento AS-90001, 01/09/2026)»: la misma frase en las dos reglas que lo ven."""
    cuando = f", {asiento.fecha:%d/%m/%Y}" if asiento.fecha else ""
    return f"Pedido ya pagado en el ERP (asiento {asiento.id}{cuando})"


@regla("R5_erp_pendiente")
def erp_pendiente(factura, refs, params):
    if refs.erp_contradictorio(factura.pedido):
        cuantos = "dos" if len(refs.asientos[factura.pedido]) == 2 else "varios"
        return Comprobacion("R5_erp_pendiente", False, f"El ERP tiene {cuantos} apuntes que no cuadran para este pedido")
    asiento = refs.asiento(factura.pedido)
    if asiento is None:
        return Comprobacion("R5_erp_pendiente", False, "No hay asiento del ERP para comprobar el estado del pedido")
    if factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_erp_pendiente", False, YA_APROBADO)
    if asiento.estado == "PAGADA":
        return Comprobacion("R5_erp_pendiente", False, ya_pagado(asiento))
    if asiento.estado != "PENDIENTE":
        return Comprobacion("R5_erp_pendiente", False, f"El ERP no da el pedido como pendiente (estado {asiento.estado})")
    return Comprobacion("R5_erp_pendiente", True)


@regla("R5_no_pagada")
def no_pagada(factura, refs, params):
    asiento = refs.asiento(factura.pedido)
    if asiento is not None and asiento.estado == "PAGADA":
        return Comprobacion("R5_no_pagada", False, ya_pagado(asiento))
    if factura.pedido and factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_no_pagada", False, YA_APROBADO)
    return Comprobacion("R5_no_pagada", True)
