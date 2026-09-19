import re

from upistas.dominio.importes import normaliza_iban
from upistas.dominio.modelos import Comprobacion
from upistas.dominio.notas import clasificar, normalizar
from upistas.dominio.reglas import regla


def _id(valor):
    return re.sub(r"[\s\u200b\ufeff]+", "", valor or "").upper()


@regla("R0_lectura")
def lectura_suficiente(factura, refs, params):
    if factura.errores_lectura:
        return Comprobacion("R0_lectura", False, "; ".join(factura.errores_lectura))
    faltan = [c for c in ("nif", "iban", "pedido", "fecha", "base", "iva", "total") if getattr(factura, c) is None]
    return Comprobacion("R0_lectura", not faltan, "Campos no verificables: " + ", ".join(faltan) if faltan else "")


@regla("R6_proveedor_referencias")
def proveedor_coherente(factura, refs, params):
    nombre = "R6_proveedor_referencias"
    asiento = refs.asientos.get(factura.pedido)
    pedido = refs.pedidos.get(factura.pedido)
    if asiento is None:
        return Comprobacion(nombre, True)
    if pedido is None or not asiento.proveedor_id or not pedido.proveedor_id:
        return Comprobacion(nombre, False, "No se puede contrastar el proveedor del pedido entre Excel y ERP")
    if _id(pedido.proveedor_id) != _id(asiento.proveedor_id):
        return Comprobacion(nombre, False, f"Proveedor contradictorio: Excel {pedido.proveedor_id}, ERP {asiento.proveedor_id}")
    proveedores = {_id(p.id): p for p in (refs.proveedores_por_id or refs.proveedores).values()}
    proveedor = proveedores.get(_id(asiento.proveedor_id))
    if proveedor is None or not proveedor.nif:
        return Comprobacion(nombre, False, f"El maestro no permite verificar el NIF del proveedor {asiento.proveedor_id}")
    if factura.nif and _id(factura.nif) != _id(proveedor.nif):
        return Comprobacion(nombre, False, "El NIF de la factura no corresponde al proveedor del ERP")
    for origen, registro in (("Excel", pedido), ("ERP", asiento)):
        if registro.nif and _id(registro.nif) != _id(proveedor.nif):
            return Comprobacion(nombre, False, f"NIF del pedido en {origen} distinto del maestro")
    return Comprobacion(nombre, True, "Identidad contrastada por ID y maestro; el NIF ausente en el pedido no se inventa")


@regla("R6_revision_interna")
def revision_interna(factura, refs, params):
    revisar = factura.pedido in refs.marcados_por_alberto
    return Comprobacion("R6_revision_interna", not revisar, "Pedido marcado en pendiente_revisar del Excel" if revisar else "")


@regla("R6_notas")
def notas_requieren_revision(factura, refs, params):
    nombre = "R6_notas"
    asiento = refs.asientos.get(factura.pedido)
    proveedor = refs.proveedores.get(factura.nif)
    for nota in factura.notas:
        if len(nota.texto) > 16384:
            return Comprobacion(nombre, False, "Nota demasiado extensa para validarla automáticamente")
        texto = normalizar(nota.texto)
        motivo = ""
        excluir_control = re.search(r"\bexcluir(?:se)?\b.{0,60}(?:calculo de precision|computo de aciertos|validacion)", texto)
        niega_exclusion = re.search(r"\bno (?:debe |debera )?excluir", texto)
        if "pide_saltar_regla" in clasificar(nota.texto) or (excluir_control and not niega_exclusion):
            motivo = "La nota pide saltarse comprobaciones"
        elif re.search(r"\bproveedor\s+(?:(?:esta|se encuentra|sigue)\s+)?(?:en|bajo) revision\b", texto):
            motivo = "La nota indica que el proveedor está en revisión"
        elif asiento is not None and asiento.estado == "PENDIENTE" and (
            re.search(r"\bpedido\s+(?:(?:ha sido|esta|fue|se encuentra)\s+)?(?:anulado|cancelado)\b", texto)
            or re.search(r"\bno procede (?:el )?pago(?: de (?:esta|la) factura)?(?:[.;,]|$)", texto)
        ):
            motivo = "La nota niega el pago o anula un pedido que el ERP da como pendiente"
        elif proveedor and factura.iban and normaliza_iban(factura.iban) == normaliza_iban(proveedor.iban) and re.search(
            r"\biban\b.{0,50}\bno coincide\b", texto
        ):
            motivo = "La nota afirma que el IBAN no coincide, pero coincide con el maestro"
        if motivo:
            return Comprobacion(nombre, False, f"{motivo}: {nota.texto[:400]}")
    return Comprobacion(nombre, True)


@regla("R5_hash_previo")
def contenido_no_aprobado(factura, refs, params):
    repetido = bool(factura.sha256 and factura.sha256 in refs.hashes_ya_aprobados)
    return Comprobacion("R5_hash_previo", not repetido, "El mismo documento ya fue aprobado en otro lote" if repetido else "")
