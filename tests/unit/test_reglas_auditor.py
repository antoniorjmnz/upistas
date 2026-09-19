from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from upistas.aplicacion.procesar import decidir
from upistas.dominio.modelos import Asiento, Factura, Pedido, Proveedor, Referencias, Resultado
from upistas.dominio.norma import Norma
from upistas.dominio.reglas import obtener

HOY = date(2026, 9, 19)
PROVEEDOR = Proveedor("P001", "Demo", "B12345678", "ES1212341234123412341234")
PEDIDO = Pedido("PO-2026-0001", "P001", "B12345678", Decimal("121"))
ASIENTO = Asiento("AS-001", PEDIDO.id, "P001", "B12345678", Decimal("121"), HOY, "PENDIENTE")
REFS = Referencias({PROVEEDOR.nif: PROVEEDOR}, {PEDIDO.id: PEDIDO}, {PEDIDO.id: ASIENTO}, HOY)
FACTURA = Factura("a.pdf", PROVEEDOR.nif, PROVEEDOR.iban, PEDIDO.id, HOY, Decimal("100"), Decimal("21"), Decimal("21"), Decimal("121"))
NORMA = Path(__file__).resolve().parents[2] / "normas" / "v3.toml"


@pytest.mark.parametrize("regla", ["R1_nif_iban", "R2_pedido_importe", "R3_iva_total", "R5_erp_pendiente", "R5_no_pagada"])
def test_regla_cumple(regla):
    assert obtener(regla)(FACTURA, REFS, {}).ok


@pytest.mark.parametrize("regla,cambio", [
    ("R1_nif_iban", {"nif": None}),
    ("R1_nif_iban", {"iban": "ES0000000000000000000000"}),
    ("R2_pedido_importe", {"pedido": "PO-2026-9999"}),
    ("R2_pedido_importe", {"total": Decimal("120")}),
    ("R3_iva_total", {"iva": Decimal("20")}),
    ("R3_iva_total", {"total": Decimal("122")}),
    ("R5_erp_pendiente", {"pedido": None}),
])
def test_regla_incumple(regla, cambio):
    assert not obtener(regla)(replace(FACTURA, **cambio), REFS, {}).ok


def test_pagada_en_erp_no_se_paga_aunque_excel_coincida():
    refs = replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, estado="PAGADA")})
    assert not obtener("R5_no_pagada")(FACTURA, refs, {}).ok
    assert Norma.desde_toml(NORMA).evaluar(FACTURA, refs).resultado == Resultado.NO_PAGAR


def test_sin_erp_escala_no_usa_abierto_del_excel():
    decision = Norma.desde_toml(NORMA).evaluar(FACTURA, replace(REFS, asientos={}))
    assert decision.resultado == Resultado.ESCALAR
    assert "ERP" in decision.motivo


def test_factura_completa_se_paga():
    assert Norma.desde_toml(NORMA).evaluar(FACTURA, REFS).resultado == Resultado.PAGAR


def test_erp_prevalece_sobre_importe_del_excel():
    refs = replace(REFS, pedidos={PEDIDO.id: replace(PEDIDO, importe=Decimal("999"))})
    assert obtener("R2_pedido_importe")(FACTURA, refs, {}).ok


def test_titularidad_en_erp_se_comprueba():
    refs = replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, proveedor_id="P002")})
    assert not obtener("R2_pedido_importe")(FACTURA, refs, {}).ok


@pytest.mark.parametrize("diferencia,ok", [("0.01", True), ("0.02", False)])
def test_tolerancia_en_decimal(diferencia, ok):
    factura = replace(FACTURA, total=Decimal("121") + Decimal(diferencia))
    assert obtener("R2_pedido_importe")(factura, REFS, {}).ok == ok


def test_pedido_ya_decidido_no_se_vuelve_a_aprobar():
    refs = replace(REFS, pedidos_ya_decididos=frozenset({PEDIDO.id}))
    assert not obtener("R5_erp_pendiente")(FACTURA, refs, {}).ok


def test_error_de_lectura_impide_pagar_aunque_los_campos_cuadren():
    campos = {"nif": PROVEEDOR.nif, "iban": PROVEEDOR.iban, "pedido": PEDIDO.id, "fecha": HOY.isoformat(), "base": 100, "iva_pct": 21, "iva": 21, "total": 121}
    from upistas.contracts.factura_extraida import FacturaExtraida

    extraida = FacturaExtraida.model_validate({
        "file_id": "a.pdf", "metodo": "texto_determinista", "checks": {},
        "documento": {"sha256": "0" * 64, "tipo": "texto", "paginas": 2},
        "campos": {k: {"valor": v, "confianza": 1} for k, v in campos.items()},
        "errores": ["Página 2: OCR sin texto"],
    })
    assert decidir("a.pdf", extraida, REFS, Norma.desde_toml(NORMA)).resultado == Resultado.ESCALAR
