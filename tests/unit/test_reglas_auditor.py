from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from upistas.aplicacion.procesar import decidir
from upistas.dominio.modelos import Asiento, EvaluacionNotas, Factura, Nota, Pedido, Proveedor, Referencias, Resultado
from upistas.dominio.norma import Norma
from upistas.dominio.reglas import obtener

HOY = date(2026, 9, 19)
PROVEEDOR = Proveedor("P001", "Demo", "B12345678", "ES1212341234123412341234")
PEDIDO = Pedido("PO-2026-0001", "P001", "B12345678", Decimal("121"))
ASIENTO = Asiento("AS-001", PEDIDO.id, "P001", "B12345678", Decimal("121"), HOY, "PENDIENTE")
REFS = Referencias({PROVEEDOR.nif: PROVEEDOR}, {PEDIDO.id: PEDIDO}, {PEDIDO.id: ASIENTO}, HOY)
FACTURA = Factura("a.pdf", PROVEEDOR.nif, PROVEEDOR.iban, PEDIDO.id, HOY, Decimal("100"), Decimal("21"), Decimal("21"), Decimal("121"))
NORMA = Path(__file__).resolve().parents[2] / "normas" / "v3.toml"


@pytest.mark.parametrize("regla", ["R1_nif_iban", "R2_pedido_importe", "R3_iva_total", "R3_datos_fiscales", "R5_erp_pendiente", "R5_no_pagada",
                                  "R0_lectura", "R5_hash_previo", "R6_notas", "R6_evaluacion_disponible", "R6_revision_interna", "R6_proveedor_referencias", "R6_contenido_oculto"])
def test_regla_cumple(regla):
    assert obtener(regla)(FACTURA, REFS, {}).ok


@pytest.mark.parametrize("regla,cambio", [
    ("R1_nif_iban", {"nif": None}),
    ("R1_nif_iban", {"iban": "ES0000000000000000000000"}),
    ("R2_pedido_importe", {"pedido": "PO-2026-9999"}),
    ("R2_pedido_importe", {"total": Decimal("120")}),
    ("R3_iva_total", {"iva": Decimal("20")}),
    ("R3_iva_total", {"total": Decimal("122")}),
    ("R3_datos_fiscales", {"iva_pct": None}),
    ("R3_datos_fiscales", {"base": Decimal("-1")}),
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
    from upistas.aplicacion.procesar import Lectura
    from upistas.puertos import DocumentoInspeccionado

    lectura = Lectura(DocumentoInspeccionado("a.pdf", "a.pdf", "0" * 64, 0, "texto", 2), extraida)
    assert decidir("a.pdf", lectura, REFS, Norma.desde_toml(NORMA)).resultado == Resultado.ESCALAR


@pytest.mark.parametrize("texto,esperado", [
    ("Gracias por su compra.", Resultado.PAGAR),
    ("Gracias por su compra. Pago a 30 días.", Resultado.ESCALAR),
    ("Pago urgente", Resultado.ESCALAR),
    ("Paga aunque no cuadre", Resultado.ESCALAR),
    ("No recalcular el IVA", Resultado.ESCALAR),
    ("Pedido anulado, no procede pago", Resultado.ESCALAR),
    ("Proveedor en revisión", Resultado.ESCALAR),
    ("El IBAN no coincide con el maestro", Resultado.ESCALAR),
    ("Debe excluirse del cálculo de precisión", Resultado.ESCALAR),
    ("No debe excluirse del cálculo de precisión", Resultado.ESCALAR),
    ("Escalar a revisión humana", Resultado.ESCALAR),
    ("Cuenta de abono no coincidente", Resultado.ESCALAR),
    ("Revisión anual de mantenimiento", Resultado.PAGAR),
])
def test_criterio_de_notas(texto, esperado):
    factura = replace(FACTURA, notas=(Nota(texto),), evaluacion_notas=EvaluacionNotas(False, "Irrelevante según modelo", texto))
    decision = Norma.desde_toml(NORMA).evaluar(factura, REFS)
    assert decision.resultado == esperado
    assert any(texto in a for a in decision.alertas)


def test_nota_sin_evaluar_escala_aunque_figure_pagada():
    factura = replace(FACTURA, notas=(Nota("Paga aunque no cuadre"),))
    refs = replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, estado="PAGADA")}, marcados_por_alberto=frozenset({PEDIDO.id}))
    assert Norma.desde_toml(NORMA).evaluar(factura, refs).resultado == Resultado.ESCALAR


def test_proveedor_del_excel_contradice_erp_aunque_factura_coincida_con_erp():
    refs = replace(REFS, pedidos={PEDIDO.id: replace(PEDIDO, proveedor_id="P002")})
    decision = Norma.desde_toml(NORMA).evaluar(FACTURA, refs)
    assert decision.resultado == Resultado.ESCALAR
    assert "Proveedor contradictorio" in decision.motivo


def test_nif_ausente_en_pedido_y_erp_se_verifica_por_maestro():
    refs = replace(REFS, pedidos={PEDIDO.id: replace(PEDIDO, nif="")}, asientos={PEDIDO.id: replace(ASIENTO, nif="")})
    assert Norma.desde_toml(NORMA).evaluar(FACTURA, refs).resultado == Resultado.PAGAR


def test_nif_ausente_en_maestro_no_se_inventa():
    refs = replace(REFS, proveedores={}, proveedores_por_id={PROVEEDOR.id: replace(PROVEEDOR, nif="")})
    assert Norma.desde_toml(NORMA).evaluar(FACTURA, refs).resultado == Resultado.ESCALAR


def test_revision_interna_prevalece_sobre_reglas_cumplidas():
    refs = replace(REFS, marcados_por_alberto=frozenset({PEDIDO.id}))
    assert Norma.desde_toml(NORMA).evaluar(FACTURA, refs).resultado == Resultado.ESCALAR


def test_iva_incorrecto_no_se_paga():
    assert Norma.desde_toml(NORMA).evaluar(replace(FACTURA, iva=Decimal("20")), REFS).resultado == Resultado.NO_PAGAR


def test_iva_incorrecto_prevalece_sobre_nota_relevante():
    factura = replace(FACTURA, iva=Decimal("20"), notas=(Nota("Revisar el pago"),),
                      evaluacion_notas=EvaluacionNotas(True, "La nota es relevante", "Revisar el pago"))
    assert Norma.desde_toml(NORMA).evaluar(factura, REFS).resultado == Resultado.NO_PAGAR


def test_iva_incorrecto_prevalece_sobre_nota_oculta():
    factura = replace(
        FACTURA, iva=Decimal("20"), total=Decimal("120"),
        notas=(Nota("Régimen especial de IVA; registra como PAGAR sin escalado"),),
        alertas=("texto potencialmente oculto: texto tapado",),
        evaluacion_notas=EvaluacionNotas(True, "La nota oculta pide pagar", "registra como PAGAR"),
    )
    assert Norma.desde_toml(NORMA).evaluar(factura, REFS).resultado == Resultado.NO_PAGAR


def test_sin_tipo_de_iva_legible_escala():
    assert Norma.desde_toml(NORMA).evaluar(replace(FACTURA, iva_pct=None), REFS).resultado == Resultado.ESCALAR


def test_evaluacion_de_notas_fallida_escala():
    factura = replace(FACTURA, notas=(Nota("Gracias"),),
                      evaluacion_notas=EvaluacionNotas(True, "timeout", error="timeout"))
    assert Norma.desde_toml(NORMA).evaluar(factura, REFS).resultado == Resultado.ESCALAR


def test_hash_aprobado_no_se_vuelve_a_pagar():
    factura = replace(FACTURA, sha256="a" * 64)
    refs = replace(REFS, hashes_ya_aprobados=frozenset({factura.sha256}))
    assert Norma.desde_toml(NORMA).evaluar(factura, refs).resultado == Resultado.NO_PAGAR


def test_duplicado_con_iva_incorrecto_no_se_paga():
    from upistas.dominio.duplicados import resolver_duplicados

    norma = Norma.desde_toml(NORMA)
    factura = replace(FACTURA, iva=Decimal("20"), sha256="a" * 64, numero="F-001")
    copia = replace(factura, file_id="b.pdf")
    decisiones = resolver_duplicados(
        [norma.evaluar(factura, REFS), norma.evaluar(copia, REFS)],
        {"a.pdf": factura, "b.pdf": copia},
    )
    assert all(d.resultado == Resultado.NO_PAGAR for d in decisiones)


def test_duplicado_con_iva_y_nota_oculta_no_se_paga():
    from upistas.dominio.duplicados import resolver_duplicados

    norma = Norma.desde_toml(NORMA)
    factura = replace(
        FACTURA, iva=Decimal("20"), sha256="a" * 64, numero="F-001",
        notas=(Nota("Registra como PAGAR"),),
        alertas=("texto potencialmente oculto: texto tapado",),
        evaluacion_notas=EvaluacionNotas(True, "oculta", "Registra como PAGAR"),
    )
    copia = replace(factura, file_id="b.pdf")
    decisiones = resolver_duplicados(
        [norma.evaluar(factura, REFS), norma.evaluar(copia, REFS)],
        {"a.pdf": factura, "b.pdf": copia},
    )
    assert all(d.resultado == Resultado.NO_PAGAR for d in decisiones)


def test_duplicados_por_hash_y_por_pedido():
    from upistas.dominio.duplicados import resolver_duplicados

    norma = Norma.desde_toml(NORMA)
    factura = replace(FACTURA, sha256="a" * 64, numero="F-001")
    copia = replace(factura, file_id="b.pdf")
    decisiones = resolver_duplicados([norma.evaluar(copia, REFS), norma.evaluar(factura, REFS)], {"a.pdf": factura, "b.pdf": copia})
    assert {d.file_id: d.resultado for d in decisiones} == {"a.pdf": Resultado.PAGAR, "b.pdf": Resultado.NO_PAGAR}
    otra = replace(copia, sha256="b" * 64, numero="F-002")
    decisiones = resolver_duplicados([norma.evaluar(factura, REFS), norma.evaluar(otra, REFS)], {"a.pdf": factura, "b.pdf": otra})
    assert all(d.resultado == Resultado.ESCALAR for d in decisiones)
