import re

from upistas.dominio.importes import normaliza_iban
from upistas.dominio.modelos import NOMBRE_CAMPO, Comprobacion, enumerar
from upistas.dominio.notas import clasificar, controles_invisibles, normalizar, solo_plazo_de_pago
from upistas.dominio.reglas import regla

# Un REVISAR del evaluador que solo habla del plazo («difiere de los 60 días del maestro»): el ADR-002 no pide comparar plazos.
_MOTIVO_SOBRE_EL_PLAZO = re.compile(r"plazo|condiciones|vencimiento|\bdias\b|\bdays\b|maestro|difier|distint|payment terms")


def _id(valor):
    return re.sub(r"[\s\u200b\ufeff]+", "", valor or "").upper()


@regla("R0_lectura")
def lectura_suficiente(factura, refs, params):
    if factura.errores_lectura:
        return Comprobacion("R0_lectura", False, "; ".join(factura.errores_lectura))
    # Un campo que el lector da por ausente con seguridad no es una duda de lectura: lo juzga su propia regla.
    faltan = [NOMBRE_CAMPO[c] for c in ("nif", "iban", "pedido", "fecha", "base", "iva", "total")
              if getattr(factura, c) is None and c not in factura.ausentes]
    return Comprobacion("R0_lectura", not faltan, "No se pudo leer: " + enumerar(faltan) if faltan else "")


def _identidad_del_pedido(factura, refs):
    """Asiento y fila del pedido, y la ficha del maestro del proveedor que el ERP les asigna."""
    asiento = refs.asiento(factura.pedido)
    pedido = refs.pedidos.get(factura.pedido)
    if asiento is None or pedido is None or not asiento.proveedor_id or not pedido.proveedor_id:
        return asiento, pedido, None
    proveedores = {_id(p.id): p for p in (refs.proveedores_por_id or refs.proveedores).values()}
    return asiento, pedido, proveedores.get(_id(asiento.proveedor_id))


@regla("R6_maestro_verificable")
def maestro_verificable(factura, refs, params):
    """Sin estos datos no se puede probar un incumplimiento de identidad: es duda, no infracción.

    Va por encima de R1 y R2 para que un maestro incompleto nunca acabe en NO_PAGAR.
    """
    nombre = "R6_maestro_verificable"
    asiento, pedido, proveedor = _identidad_del_pedido(factura, refs)
    if asiento is None:
        return Comprobacion(nombre, True)
    if pedido is None or not asiento.proveedor_id or not pedido.proveedor_id:
        return Comprobacion(nombre, False, "No se puede contrastar el proveedor del pedido entre Excel y ERP")
    if proveedor is None or not proveedor.nif:
        return Comprobacion(nombre, False, f"El maestro no permite verificar el NIF del proveedor {asiento.proveedor_id}")
    if not proveedor.iban:
        return Comprobacion(nombre, False, f"El maestro no permite verificar el IBAN del proveedor {asiento.proveedor_id}")
    return Comprobacion(nombre, True)


@regla("R6_proveedor_referencias")
def proveedor_coherente(factura, refs, params):
    nombre = "R6_proveedor_referencias"
    asiento, pedido, proveedor = _identidad_del_pedido(factura, refs)
    if asiento is None or pedido is None or not asiento.proveedor_id or not pedido.proveedor_id:
        return Comprobacion(nombre, True)
    if _id(pedido.proveedor_id) != _id(asiento.proveedor_id):
        return Comprobacion(nombre, False, f"Proveedor contradictorio: Excel {pedido.proveedor_id}, ERP {asiento.proveedor_id}")
    if proveedor is None or not proveedor.nif:
        return Comprobacion(nombre, True)
    if factura.nif and _id(factura.nif) != _id(proveedor.nif):
        return Comprobacion(nombre, False, "El NIF de la factura no corresponde al proveedor del ERP")
    for origen, registro in (("Excel", pedido), ("ERP", asiento)):
        if registro.nif and _id(registro.nif) != _id(proveedor.nif):
            return Comprobacion(nombre, False, f"NIF del pedido en {origen} distinto del maestro")
    sin_nif = [origen for origen, registro in (("Excel", pedido), ("ERP", asiento)) if not registro.nif]
    if sin_nif:
        return Comprobacion(nombre, True, f"Identidad contrastada con el maestro por ID; el NIF ausente en el pedido ({' y '.join(sin_nif)}) no se inventa")
    return Comprobacion(nombre, True, "Identidad contrastada con el maestro por ID y NIF")


@regla("R6_revision_interna")
def revision_interna(factura, refs, params):
    revisar = factura.pedido in refs.marcados_por_alberto
    detalle = "El pedido está apuntado para revisar (marca pendiente_revisar del maestro)" if revisar else ""
    return Comprobacion("R6_revision_interna", not revisar, detalle)


@regla("R6_notas")
def notas_requieren_revision(factura, refs, params):
    nombre = "R6_notas"
    notas = tuple(n for n in factura.notas if n.texto.strip())
    if not notas:
        return Comprobacion(nombre, True)
    evaluacion = factura.evaluacion_notas
    if evaluacion is None:
        return Comprobacion(nombre, False, "Notas sin evaluación: requieren revisión humana")
    # Una nota que solo es un plazo de pago es un dato, no una instrucción: no escala por sí sola, ni porque el
    # evaluador compare el plazo con el maestro. Sí escala si el evaluador ve otra cosa o si la nota pide algo más.
    solo_plazos = all(solo_plazo_de_pago(n.texto) for n in notas)
    revisar_por_el_plazo = solo_plazos and bool(_MOTIVO_SOBRE_EL_PLAZO.search(normalizar(evaluacion.motivo)))
    if evaluacion.error or (evaluacion.requiere_revision and not revisar_por_el_plazo):
        # El modelo y la versión del prompt quedan en la traza (reglas[]); el motivo va en llano.
        detalle = f"Evaluación de notas [{evaluacion.modelo or 'no disponible'}; {evaluacion.version_prompt}]: {evaluacion.motivo}"
        motivo = evaluacion.motivo.strip()
        if evaluacion.evidencia:
            detalle += f" | Evidencia: {evaluacion.evidencia}"
            motivo = f"{motivo.rstrip('.')}. Evidencia: «{' '.join(evaluacion.evidencia.split())}»"
        return Comprobacion(nombre, False, detalle, motivo)
    asiento = refs.asiento(factura.pedido)
    proveedor = refs.proveedores.get(factura.nif)
    for nota in notas:
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
        if not motivo and not solo_plazo_de_pago(nota.texto) and (clasificar(nota.texto) != ("otra",) or re.search(
            r"\b(?:pagos?|vencimientos?|importe|iva|iban|nif|erp|anulacion|cancelacion|aprobacion)\b", texto
        )):
            motivo = "La nota contiene información operativa o instrucciones; no es inequívocamente irrelevante"
        if motivo:
            return Comprobacion(nombre, False, f"{motivo}: {nota.texto[:400]}")
    return Comprobacion(nombre, True)


@regla("R6_evaluacion_disponible")
def evaluacion_disponible(factura, refs, params):
    if not any(n.texto.strip() for n in factura.notas):
        return Comprobacion("R6_evaluacion_disponible", True)
    evaluacion = factura.evaluacion_notas
    ok = evaluacion is not None and not evaluacion.error
    return Comprobacion("R6_evaluacion_disponible", ok, "" if ok else "No se dispone de una evaluación válida de las notas")


@regla("R6_contenido_oculto")
def contenido_oculto(factura, refs, params):
    avisos = [a for a in factura.alertas if a.startswith((
        "texto potencialmente oculto:", "visibilidad del texto no verificable:", "texto dibujado letra a letra",
    ))]
    codigos = sorted({c for n in factura.notas for c in controles_invisibles(n.texto)})
    if codigos:
        avisos.append("caracteres de control o invisibles en notas: " + ", ".join(codigos))
    detalle = "; ".join(avisos)
    return Comprobacion("R6_contenido_oculto", not avisos, detalle, f"El fichero trae {detalle}" if avisos else "")


@regla("R5_hash_previo")
def contenido_no_aprobado(factura, refs, params):
    repetido = bool(factura.sha256 and factura.sha256 in refs.hashes_ya_aprobados)
    return Comprobacion("R5_hash_previo", not repetido, "El mismo documento ya fue aprobado en otro lote" if repetido else "")
