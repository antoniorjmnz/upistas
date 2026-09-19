"""Traducción entre contratos (JSON en los bordes) y modelos de dominio."""
from __future__ import annotations

from decimal import Decimal

from upistas.contracts.decision import Decision as DecisionContrato
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.importes import normaliza_iban, parse_fecha
from upistas.dominio.modelos import Decision, Factura, Nota

# Por debajo de esta confianza un campo se trata como no leído (y las reglas lo verán como duda).
CONFIANZA_MINIMA = 0.8

CAMPOS = ("nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total", "numero_factura", "proveedor_nombre", "cliente_cif")


def a_factura(extraida: FacturaExtraida) -> Factura:
    c = extraida.campos
    valores: dict[str, object] = {}
    ausentes: set[str] = set()
    no_leidos: set[str] = set()
    for nombre in CAMPOS:
        campo = getattr(c, nombre, None)
        if campo is None or campo.valor is None:
            # valor null + confianza alta = seguro que no está; confianza baja = no se pudo leer
            (ausentes if campo is not None and campo.confianza >= CONFIANZA_MINIMA else no_leidos).add(nombre)
            valores[nombre] = None
        elif campo.confianza < CONFIANZA_MINIMA:
            no_leidos.add(nombre)
            valores[nombre] = None
        else:
            valores[nombre] = campo.valor

    def dec(nombre: str) -> Decimal | None:
        v = valores[nombre]
        return Decimal(str(v)) if v is not None else None

    return Factura(
        file_id=extraida.file_id,
        nif=valores["nif"],
        iban=normaliza_iban(valores["iban"]),
        pedido=valores["pedido"],
        fecha=parse_fecha(valores["fecha"] or "") if valores["fecha"] else None,
        base=dec("base"),
        iva_pct=dec("iva_pct"),
        iva=dec("iva"),
        total=dec("total"),
        lineas=tuple(Decimal(str(linea.importe)) for linea in (extraida.lineas or [])),
        numero=valores["numero_factura"],
        proveedor_nombre=valores["proveedor_nombre"],
        cliente_cif=valores["cliente_cif"],
        notas=tuple(Nota(n.texto, tuple(cat.value for cat in n.categorias)) for n in (extraida.notas or [])),
        alertas=tuple(extraida.documento.alertas or []),
        tipo_documento=extraida.documento.tipo.value,
        metodo=extraida.metodo.value,
        ausentes=frozenset(ausentes),
        no_leidos=frozenset(no_leidos),
        sha256=extraida.documento.sha256,
        errores_lectura=tuple(extraida.errores or []),
    )


def a_outcome(decision: Decision, version_datos: str = "", metodo: str | None = None) -> dict:
    """Una línea de outcomes.jsonl (valida contra contracts/decision.schema.json)."""
    contrato = DecisionContrato(
        file_id=decision.file_id,
        result=decision.resultado.value,
        motivo=decision.motivo,
        norma=decision.norma,
        pedido=decision.pedido,
        reglas=[{"id": c.regla, "ok": c.ok, "detalle": c.detalle or None} for c in decision.comprobaciones],
        alertas=list(decision.alertas) or None,
        metodo=metodo,
        version_datos=version_datos or None,
    )
    return contrato.model_dump(mode="json", exclude_none=True)
