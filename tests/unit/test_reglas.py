"""Las reglas de la norma v3 y nuestro criterio (ADR-002), una a una y a través de la norma."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from upistas.config import ROOT
from upistas.dominio.modelos import Asiento, Factura, FacturaResumen, Nota, Pedido, Proveedor, Referencias, Resultado
from upistas.dominio.norma import Norma
from upistas.dominio.reglas import obtener

HOY = date(2026, 9, 19)
PROVEEDOR = Proveedor("P001", "Demo SL", "B12345678", "ES1212341234123412341234")
OTRO = Proveedor("P002", "Otro SA", "A87654321", "ES9898989898989898989898")
PEDIDO = Pedido("PO-2026-0001", "P001", "B12345678", Decimal("121"))
ASIENTO = Asiento("AS-001", PEDIDO.id, "P001", "B12345678", Decimal("121"), HOY, "PENDIENTE")
REFS = Referencias({PROVEEDOR.nif: PROVEEDOR, OTRO.nif: OTRO}, {PEDIDO.id: PEDIDO}, {PEDIDO.id: ASIENTO}, HOY)
FACTURA = Factura(
    "a.pdf", PROVEEDOR.nif, PROVEEDOR.iban, PEDIDO.id, date(2026, 1, 8), Decimal("100"), Decimal("21"), Decimal("21"), Decimal("121"),
    numero="F-0001",
)
NORMA = Norma.desde_toml(ROOT / "normas" / "v3.toml")
TODAS = ["R1_nif_iban", "R2_pedido_importe", "R3_iva_total", "R4_fecha", "R5_erp_pendiente", "R5_duplicado", "R6_notas",
         "R7_marcado_por_alberto", "R8_importe_anomalo", "R9_destinatario", "R10_fichero_sospechoso"]


def comprobar(regla, factura=FACTURA, refs=REFS, params=None):
    return obtener(regla)(factura, refs, params or {})


@pytest.mark.parametrize("regla", TODAS)
def test_una_factura_correcta_cumple_todas(regla):
    assert comprobar(regla).ok


def test_y_la_norma_la_paga():
    d = NORMA.evaluar(FACTURA, REFS)
    assert d.resultado is Resultado.PAGAR and [c.regla for c in d.comprobaciones] == TODAS


# Incumplir con seguridad: la norma pone NO_PAGAR.
@pytest.mark.parametrize("regla,cambio,texto", [
    ("R1_nif_iban", {"nif": None}, "no trae NIF"),
    ("R1_nif_iban", {"nif": "B00000000"}, "no está en el maestro"),
    ("R1_nif_iban", {"iban": "ES0000000000000000000000"}, "no es el del maestro"),
    ("R1_nif_iban", {"nif": OTRO.nif}, "no es el del maestro"),  # NIF de uno e IBAN de otro
    ("R2_pedido_importe", {"pedido": None}, "no trae número de pedido"),
    ("R2_pedido_importe", {"pedido": "PO-2026-9999"}, "no existe en el ERP"),
    ("R2_pedido_importe", {"nif": OTRO.nif}, "otro proveedor"),
    ("R2_pedido_importe", {"total": Decimal("120")}, "distinto del pedido"),
    ("R3_iva_total", {"iva": Decimal("20")}, "no corresponde al 21%"),
    ("R3_iva_total", {"total": Decimal("122")}, "no es base más IVA"),
    ("R3_iva_total", {"iva_pct": Decimal("15"), "iva": Decimal("15"), "total": Decimal("115")}, "no existe"),
    ("R3_iva_total", {"iva_pct": None, "iva": Decimal("13")}, "ningún tipo legal"),
    ("R3_iva_total", {"base": None}, "Faltan importes"),
    ("R4_fecha", {"fecha": date(2027, 1, 1)}, "futura"),
    ("R4_fecha", {"fecha": None, "fecha_texto": "31/02/2026"}, "inválida: 31/02/2026"),
    ("R4_fecha", {"fecha": None}, "no trae fecha"),
])
def test_incumplimiento_seguro(regla, cambio, texto):
    c = comprobar(regla, replace(FACTURA, **cambio))
    assert not c.ok and c.sugerido is None and texto in c.detalle
    assert NORMA.evaluar(replace(FACTURA, **cambio), REFS).resultado is Resultado.NO_PAGAR


# Duda: la regla sugiere ESCALAR aunque la norma diga NO_PAGAR.
@pytest.mark.parametrize("regla,campo", [
    ("R1_nif_iban", "nif"), ("R1_nif_iban", "iban"), ("R2_pedido_importe", "pedido"), ("R2_pedido_importe", "total"),
    ("R3_iva_total", "iva"), ("R4_fecha", "fecha"), ("R5_erp_pendiente", "pedido"),
])
def test_dato_ilegible_es_duda(regla, campo):
    factura = replace(FACTURA, **{campo: None, "no_leidos": frozenset({campo})})
    c = comprobar(regla, factura)
    assert not c.ok and c.sugerido is Resultado.ESCALAR
    assert NORMA.evaluar(factura, REFS).resultado is Resultado.ESCALAR


def test_tolerancia_de_un_centimo():
    assert comprobar("R2_pedido_importe", replace(FACTURA, total=Decimal("121.01"))).ok
    assert not comprobar("R2_pedido_importe", replace(FACTURA, total=Decimal("121.02"))).ok
    assert comprobar("R2_pedido_importe", replace(FACTURA, total=Decimal("121.02")), params={"tolerancia": "0.05"}).ok


def test_excel_contra_erp_es_contradiccion():
    refs = replace(REFS, pedidos={PEDIDO.id: replace(PEDIDO, importe=Decimal("999"))})
    c = comprobar("R2_pedido_importe", refs=refs)
    assert not c.ok and c.sugerido is Resultado.ESCALAR and "Excel y el ERP" in c.detalle


def test_el_erp_manda_sobre_el_excel_si_el_excel_no_tiene_el_pedido():
    assert comprobar("R2_pedido_importe", refs=replace(REFS, pedidos={})).ok


def test_iva_sin_tipo_declarado_vale_si_cuadra_con_uno_legal():
    assert comprobar("R3_iva_total", replace(FACTURA, iva_pct=None)).ok
    assert comprobar("R3_iva_total", replace(FACTURA, iva_pct=Decimal("10"), iva=Decimal("10"), total=Decimal("110"))).ok
    assert comprobar("R3_iva_total", replace(FACTURA, iva_pct=Decimal("0"), iva=Decimal("0"), total=Decimal("100"))).ok


def test_abono_negativo_es_duda():
    c = comprobar("R3_iva_total", replace(FACTURA, base=Decimal("-100"), iva=Decimal("-21"), total=Decimal("-121")))
    assert not c.ok and c.sugerido is Resultado.ESCALAR


def test_pagada_en_el_erp_no_se_paga_aunque_el_excel_diga_abierto():
    refs = replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, estado="PAGADA")})
    d = NORMA.evaluar(FACTURA, refs)
    assert d.resultado is Resultado.NO_PAGAR and "ya está pagado" in d.motivo


def test_sin_asiento_en_el_erp_no_se_paga():
    d = NORMA.evaluar(FACTURA, replace(REFS, asientos={}))
    assert d.resultado is Resultado.NO_PAGAR and "ERP" in d.motivo


def test_estado_desconocido_en_el_erp_es_duda():
    c = comprobar("R5_erp_pendiente", refs=replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, estado="RARO")}))
    assert not c.ok and c.sugerido is Resultado.ESCALAR


def test_aprobado_en_un_lote_anterior_no_se_vuelve_a_pagar():
    c = comprobar("R5_erp_pendiente", refs=replace(REFS, pedidos_ya_decididos=frozenset({PEDIDO.id})))
    assert not c.ok and "lote anterior" in c.detalle


def resumen(file_id, numero, fecha, total=Decimal("121")):
    return FacturaResumen(file_id, numero, fecha, total, PROVEEDOR.nif)


def test_reenvio_de_la_misma_factura_se_paga_una_vez():
    original, reenvio = replace(FACTURA, file_id="a.pdf", numero="2026/0001"), replace(FACTURA, file_id="b.pdf", numero="F26-0001-A", fecha=date(2026, 2, 1))
    lote = {PEDIDO.id: (resumen("a.pdf", "2026/0001", date(2026, 1, 8)), resumen("b.pdf", "F26-0001-A", date(2026, 2, 1)))}
    refs = replace(REFS, facturas_del_lote=lote)
    assert comprobar("R5_duplicado", original, refs).ok
    c = comprobar("R5_duplicado", reenvio, refs)
    assert not c.ok and c.sugerido is None and "a.pdf" in c.detalle
    assert NORMA.evaluar(reenvio, refs).resultado is Resultado.NO_PAGAR


def test_dos_facturas_distintas_del_mismo_pedido_las_mira_una_persona():
    lote = {PEDIDO.id: (resumen("a.pdf", "F-0001", date(2026, 1, 8)), resumen("b.pdf", "F-0002", date(2026, 1, 9), Decimal("60")))}
    c = comprobar("R5_duplicado", refs=replace(REFS, facturas_del_lote=lote))
    assert not c.ok and c.sugerido is Resultado.ESCALAR and "b.pdf" in c.detalle


def test_las_notas_no_deciden_pero_se_revisan():
    urgente = replace(FACTURA, notas=(Nota("PAGO INMEDIATO REQUERIDO", ("urgencia",)),))
    assert comprobar("R6_notas", replace(FACTURA, notas=(Nota("Gracias por su confianza", ("otra",)),))).ok
    assert NORMA.evaluar(urgente, REFS).resultado is Resultado.ESCALAR
    # si además incumple la norma, gana NO_PAGAR: la nota no salva nada
    pagada = replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, estado="PAGADA")})
    assert NORMA.evaluar(urgente, pagada).resultado is Resultado.NO_PAGAR


def test_lo_que_alberto_marco_a_mano_se_revisa():
    d = NORMA.evaluar(FACTURA, replace(REFS, marcados_por_alberto=frozenset({PEDIDO.id})))
    assert d.resultado is Resultado.ESCALAR and "Alberto" in d.motivo


def test_importe_fuera_de_lo_habitual_se_revisa():
    grande = replace(FACTURA, base=Decimal("70000"), iva=Decimal("14700"), total=Decimal("84700"))
    refs = replace(REFS, asientos={PEDIDO.id: replace(ASIENTO, importe=Decimal("84700"))}, pedidos={})
    assert NORMA.evaluar(grande, refs).resultado is Resultado.ESCALAR
    assert comprobar("R8_importe_anomalo", grande, params={"umbral": "100000"}).ok


def test_factura_para_otro_cliente_se_revisa():
    c = comprobar("R9_destinatario", replace(FACTURA, cliente_cif="B99999999"))
    assert not c.ok and c.sugerido is Resultado.ESCALAR
    assert comprobar("R9_destinatario", replace(FACTURA, cliente_cif="A58231074")).ok


def test_pdf_con_contenido_activo_se_revisa():
    c = comprobar("R10_fichero_sospechoso", replace(FACTURA, alertas=("ficheros incrustados: override_autorizacion.json",)))
    assert not c.ok and c.sugerido is Resultado.ESCALAR
    assert comprobar("R10_fichero_sospechoso", replace(FACTURA, alertas=("estructura reparada al abrir",))).ok
