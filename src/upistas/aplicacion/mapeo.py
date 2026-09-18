"""Traducción entre contratos (JSON en los bordes) y modelos de dominio."""
from __future__ import annotations

from decimal import Decimal

from upistas.contracts.decision import Decision as DecisionContrato
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.importes import normaliza_iban, parse_fecha
from upistas.dominio.modelos import Decision, Factura

# Por debajo de esta confianza un campo se trata como no leído (y las reglas lo verán como duda).
CONFIANZA_MINIMA = 0.8


def a_factura(extraida: FacturaExtraida) -> Factura:
    c = extraida.campos

    def valor(campo):
        return campo.valor if campo is not None and campo.confianza >= CONFIANZA_MINIMA else None

    def dec(campo):
        v = valor(campo)
        return Decimal(str(v)) if v is not None else None

    return Factura(
        file_id=extraida.file_id,
        nif=valor(c.nif),
        iban=normaliza_iban(valor(c.iban)),
        pedido=valor(c.pedido),
        fecha=parse_fecha(valor(c.fecha) or ""),
        base=dec(c.base),
        iva_pct=dec(c.iva_pct),
        iva=dec(c.iva),
        total=dec(c.total),
        lineas=tuple(Decimal(str(linea.importe)) for linea in (extraida.lineas or [])),
    )


def a_outcome(decision: Decision) -> dict:
    """Una línea de outcomes.jsonl (valida contra contracts/decision.schema.json)."""
    contrato = DecisionContrato(
        file_id=decision.file_id,
        result=decision.resultado.value,
        motivo=decision.motivo,
        norma=decision.norma,
        pedido=decision.pedido,
        reglas=[{"id": c.regla, "ok": c.ok, "detalle": c.detalle or None} for c in decision.comprobaciones],
    )
    return contrato.model_dump(mode="json", exclude_none=True)
