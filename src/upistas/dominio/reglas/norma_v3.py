"""Las reglas de la norma de pagos v3 y las de nuestro criterio (docs/adr/002-criterio.md).

Cada regla devuelve una Comprobacion. Cuando falla con seguridad, la consecuencia la pone la
norma (`normas/v3.toml`, normalmente NO_PAGAR). Cuando no puede decidir (dato ilegible, fuentes
que se contradicen, algo que solo Alberto puede confirmar) sugiere ESCALAR.

Basadas en las de Pablo Sáez (R1-R5) adaptadas al criterio acordado.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from upistas.dominio.modelos import CIF_ALBERTO, Comprobacion, Resultado
from upistas.dominio.reglas import regla

ESCALAR = Resultado.ESCALAR


def _tol(params) -> Decimal:
    return Decimal(str(params.get("tolerancia", "0.01")))


def _duda(nombre: str, detalle: str) -> Comprobacion:
    return Comprobacion(nombre, False, detalle, sugerido=ESCALAR)


# --- 1. NIF en el maestro y el IBAN coincide -------------------------------------------------


@regla("R1_nif_iban")
def nif_iban(factura, refs, params):
    if factura.dudoso("nif"):
        return _duda("R1_nif_iban", "NIF ilegible")
    if not factura.nif:
        return Comprobacion("R1_nif_iban", False, "La factura no trae NIF")
    proveedor = refs.proveedores.get(factura.nif)
    if proveedor is None:
        return Comprobacion("R1_nif_iban", False, f"El NIF {factura.nif} no está en el maestro de proveedores")
    if factura.dudoso("iban"):
        return _duda("R1_nif_iban", "IBAN ilegible")
    if not factura.iban:
        return Comprobacion("R1_nif_iban", False, "La factura no trae IBAN")
    if factura.iban != proveedor.iban:
        return Comprobacion("R1_nif_iban", False, f"El IBAN no es el del maestro para {proveedor.nombre}")
    return Comprobacion("R1_nif_iban", True)


# --- 2. El pedido existe, es del proveedor y el importe coincide -----------------------------


@regla("R2_pedido_importe")
def pedido_importe(factura, refs, params):
    if factura.dudoso("pedido"):
        return _duda("R2_pedido_importe", "Número de pedido ilegible")
    if not factura.pedido:
        return Comprobacion("R2_pedido_importe", False, "La factura no trae número de pedido")
    asiento = refs.asientos.get(factura.pedido)
    if asiento is None:
        return Comprobacion("R2_pedido_importe", False, f"El pedido {factura.pedido} no existe en el ERP")
    excel = refs.pedidos.get(factura.pedido)
    if excel is not None and (excel.proveedor_id != asiento.proveedor_id or abs(excel.importe - asiento.importe) > _tol(params)):
        return _duda("R2_pedido_importe", f"El Excel y el ERP no coinciden sobre el pedido {factura.pedido}")
    if factura.dudoso("nif"):
        return _duda("R2_pedido_importe", "NIF ilegible: no se puede comprobar de quién es el pedido")
    proveedor = refs.proveedores.get(factura.nif) if factura.nif else None
    if proveedor is None:
        return Comprobacion("R2_pedido_importe", False, f"No se puede comprobar que el pedido {factura.pedido} sea del emisor: su NIF no está en el maestro")
    if asiento.proveedor_id != proveedor.id or (asiento.nif and asiento.nif != factura.nif):
        return Comprobacion("R2_pedido_importe", False, f"El pedido {factura.pedido} es de otro proveedor")
    if factura.dudoso("total"):
        return _duda("R2_pedido_importe", "Total ilegible")
    if factura.total is None:
        return Comprobacion("R2_pedido_importe", False, "La factura no trae total")
    if abs(factura.total - asiento.importe) > _tol(params):
        return Comprobacion("R2_pedido_importe", False, f"Total {factura.total:.2f} € distinto del pedido ({asiento.importe:.2f} €)")
    return Comprobacion("R2_pedido_importe", True)


# --- 3. IVA bien calculado y total = base + IVA ----------------------------------------------


@regla("R3_iva_total")
def iva_total(factura, refs, params):
    campos = ("base", "iva", "iva_pct", "total")
    ilegibles = [c for c in campos if factura.dudoso(c)]
    if ilegibles:
        return _duda("R3_iva_total", f"Importes ilegibles: {', '.join(ilegibles)}")
    base, iva, pct, total = factura.base, factura.iva, factura.iva_pct, factura.total
    tol = _tol(params)
    tipos = [Decimal(str(t)) for t in params.get("tipos_iva", [21, 10, 4, 0])]

    def cuota(tipo: Decimal) -> Decimal:
        return (base * tipo / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if pct is None and base is not None and iva is not None:
        # La factura no declara el tipo: vale si la cuota corresponde a alguno de los legales.
        pct = next((t for t in tipos if abs(cuota(t) - iva) <= tol), None)
        if pct is None:
            return Comprobacion("R3_iva_total", False, f"La cuota de IVA {iva:.2f} € no corresponde a ningún tipo legal sobre {base:.2f} €")
    if None in (base, iva, pct, total):
        faltan = [c for c, v in zip(campos, (base, iva, pct, total)) if v is None]
        return Comprobacion("R3_iva_total", False, f"Faltan importes en la factura: {', '.join(faltan)}")
    if min(base, iva, total) < 0:
        return _duda("R3_iva_total", "Importe negativo: puede ser un abono")
    if pct not in tipos:
        return Comprobacion("R3_iva_total", False, f"Tipo de IVA {pct}% no existe")
    if abs(iva - cuota(pct)) > tol:
        return Comprobacion("R3_iva_total", False, f"La cuota de IVA {iva:.2f} € no corresponde al {pct}% de {base:.2f} €")
    if abs(total - base - iva) > tol:
        return Comprobacion("R3_iva_total", False, f"El total {total:.2f} € no es base más IVA ({base + iva:.2f} €)")
    return Comprobacion("R3_iva_total", True)


# --- 4. Fecha válida y no futura ------------------------------------------------------------


@regla("R4_fecha")
def fecha_valida_y_no_futura(factura, refs, params):
    if factura.dudoso("fecha"):
        return _duda("R4_fecha", "Fecha ilegible")
    if factura.fecha is None:
        if factura.fecha_texto:
            return Comprobacion("R4_fecha", False, f"Fecha inválida: {factura.fecha_texto}")
        return Comprobacion("R4_fecha", False, "La factura no trae fecha")
    if factura.fecha > refs.hoy:
        return Comprobacion("R4_fecha", False, f"Fecha futura: {factura.fecha.isoformat()}")
    return Comprobacion("R4_fecha", True)


# --- 5. Pedido pendiente en el ERP; nunca pagar dos veces -----------------------------------


@regla("R5_erp_pendiente")
def erp_pendiente(factura, refs, params):
    if not factura.pedido or factura.dudoso("pedido"):
        return _duda("R5_erp_pendiente", "Sin pedido legible no se puede comprobar el estado en el ERP")
    asiento = refs.asientos.get(factura.pedido)
    if asiento is None:
        return Comprobacion("R5_erp_pendiente", False, f"No hay asiento en el ERP para {factura.pedido}")
    if asiento.estado == "PAGADA":
        return Comprobacion("R5_erp_pendiente", False, f"El pedido {factura.pedido} ya está pagado según el ERP")
    if asiento.estado != "PENDIENTE":
        return _duda("R5_erp_pendiente", f"Estado desconocido en el ERP: {asiento.estado}")
    if factura.pedido in refs.pedidos_ya_decididos:
        return Comprobacion("R5_erp_pendiente", False, f"El pedido {factura.pedido} ya se aprobó para pago en un lote anterior")
    return Comprobacion("R5_erp_pendiente", True)


def _clave_numero(numero: str | None) -> str | None:
    """'2026/0233-A' y 'F26-0233' son la misma factura: se comparan por su último grupo de dígitos."""
    if not numero:
        return None
    grupos = re.findall(r"\d{3,}", numero)
    return grupos[-1] if grupos else numero


@regla("R5_duplicado")
def duplicado_en_el_lote(factura, refs, params):
    """Dos facturas del mismo pedido en el lote: si es la misma reenviada, se paga la original
    (la de fecha más antigua); si son distintas, decide una persona."""
    if not factura.pedido:
        return Comprobacion("R5_duplicado", True)
    otras = [o for o in refs.facturas_del_lote.get(factura.pedido, ()) if o.file_id != factura.file_id]
    if not otras:
        return Comprobacion("R5_duplicado", True)
    mi_clave = _clave_numero(factura.numero)
    mismas = [o for o in otras if mi_clave and _clave_numero(o.numero) == mi_clave and o.total == factura.total]
    distintas = [o for o in otras if o not in mismas]
    if distintas:
        return _duda("R5_duplicado", f"Otra factura distinta del mismo pedido en el lote: {', '.join(o.file_id for o in distintas)}")
    if factura.fecha is None or any(o.fecha is None for o in mismas):
        return _duda("R5_duplicado", "Factura reenviada y no se puede saber cuál es la original")
    original = min([(factura.fecha, factura.file_id)] + [(o.fecha, o.file_id) for o in mismas])
    if original[1] == factura.file_id:
        return Comprobacion("R5_duplicado", True, f"Original; reenviada después como {', '.join(o.file_id for o in mismas)}")
    return Comprobacion("R5_duplicado", False, f"Reenvío de la factura ya presentada como {original[1]}")


# --- Nuestro criterio: contradicciones y anomalías que debe ver una persona ------------------


@regla("R6_notas")
def notas_que_contradicen(factura, refs, params):
    """El texto de una factura nunca decide. Si intenta hacerlo o afirma algo que solo Alberto
    puede confirmar, la factura se revisa aunque cumpla todo lo demás."""
    sospechosas = [n for n in factura.notas if any(c in ("dirigida_al_sistema", "pide_saltar_regla", "info_negocio", "urgencia") for c in n.categorias)]
    if not sospechosas:
        return Comprobacion("R6_notas", True)
    return _duda("R6_notas", "La factura trae texto que intenta influir en la decisión: " + " | ".join(n.texto[:90] for n in sospechosas[:2]))


@regla("R7_marcado_por_alberto")
def marcado_por_alberto(factura, refs, params):
    if factura.pedido and factura.pedido in refs.marcados_por_alberto:
        return _duda("R7_marcado_por_alberto", f"Alberto apuntó el pedido {factura.pedido} como pendiente de revisar")
    return Comprobacion("R7_marcado_por_alberto", True)


@regla("R8_importe_anomalo")
def importe_anomalo(factura, refs, params):
    umbral = Decimal(str(params.get("umbral", "20000")))
    if factura.total is not None and factura.total > umbral:
        return _duda("R8_importe_anomalo", f"Importe fuera de lo habitual: {factura.total:.2f} € (umbral {umbral:.0f} €)")
    return Comprobacion("R8_importe_anomalo", True)


@regla("R9_destinatario")
def destinatario(factura, refs, params):
    if factura.cliente_cif and factura.cliente_cif != CIF_ALBERTO:
        return _duda("R9_destinatario", f"La factura va dirigida a otro cliente (CIF {factura.cliente_cif})")
    return Comprobacion("R9_destinatario", True)


@regla("R10_fichero_sospechoso")
def fichero_sospechoso(factura, refs, params):
    raras = [a for a in factura.alertas if any(p in a for p in ("JavaScript", "incrustados", "acción automática", "multimedia"))]
    if raras:
        return _duda("R10_fichero_sospechoso", "El PDF trae contenido que no tiene sentido en una factura: " + ", ".join(raras))
    return Comprobacion("R10_fichero_sospechoso", True)
