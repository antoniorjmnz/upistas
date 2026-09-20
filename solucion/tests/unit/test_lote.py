from datetime import date
from decimal import Decimal

from upistas.adaptadores.fuentes.memoria import ErpEnMemoria, MaestroEnMemoria
from upistas.aplicacion.lote import comparar, decidir_lote, resumen
from upistas.aplicacion.referencias import construir_referencias
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.modelos import Asiento, Pedido, Proveedor
from upistas.dominio.norma import Norma
from upistas.puertos import DecisionGuardada, RegistroLectura

PROV = Proveedor("P001", "Suministros Levante S.L.", "B46102331", "ES2100491500051234567890")


def extraida(file_id="a.pdf", pedido="PO-2026-0096", fecha="2026-01-08", total=3012.89, metodo="texto_determinista"):
    campo = lambda v: {"valor": v, "confianza": 1.0}  # noqa: E731
    return FacturaExtraida.model_validate({
        "file_id": file_id, "metodo": metodo, "lector": "pdf_texto",
        "documento": {"sha256": "x" * 64, "tipo": "texto", "paginas": 1, "alertas": []},
        "campos": {"nif": campo("B46102331"), "iban": campo("ES2100491500051234567890"), "pedido": campo(pedido), "fecha": campo(fecha),
                   "base": campo(2489.99), "iva_pct": campo(21), "iva": campo(522.9), "total": campo(total),
                   "numero_factura": campo("2026/11604")},
        "lineas": [], "notas": [], "checks": {"total_cuadra": True},
    })


def registro(file_id, ext=None, tipo="texto"):
    return RegistroLectura(lote="lote1", file_id=file_id, ruta=f"/x/{file_id}", sha256="s" + file_id, bytes=10, tipo=tipo, paginas=1,
                           alertas=(), extraida=ext, intentos=(("pdf_texto", "no pudo"),) if ext is None else ())


def norma_v(tmp_path):
    ruta = tmp_path / "n.toml"
    ruta.write_text('version = "t"\n[reglas.R4_fecha]\nsi_falla = "NO_PAGAR"\n', encoding="utf-8")
    return Norma.desde_toml(ruta)


def test_las_referencias_traen_todo_lo_que_pueden_mirar_las_reglas():
    maestro = MaestroEnMemoria([PROV], [Pedido("PO-2026-0096", "P001", "B46102331", Decimal("3012.89"))], frozenset({"PO-2026-0007"}), version="ex1")
    erp = ErpEnMemoria([Asiento("AS-00096", "PO-2026-0096", "P001", "B46102331", Decimal("3012.89"), date(2026, 1, 8), "PENDIENTE")])
    lecturas = [registro("a.pdf", extraida("a.pdf")), registro("b.pdf", extraida("b.pdf", fecha="2026-01-12")), registro("c.pdf")]
    refs = construir_referencias(maestro, erp, lecturas, date(2026, 9, 18), "erp1", frozenset({"PO-2026-0001"}))
    assert refs.proveedores["B46102331"] is PROV
    assert refs.asiento("PO-2026-0096").estado == "PENDIENTE"
    assert refs.marcados_por_alberto == {"PO-2026-0007"}
    assert refs.pedidos_ya_decididos == {"PO-2026-0001"}
    assert [f.file_id for f in refs.facturas_del_lote["PO-2026-0096"]] == ["a.pdf", "b.pdf"]  # dos facturas del mismo pedido
    assert refs.version_datos == "erp1+ex1"


def test_construir_referencias_no_se_para_si_el_erp_trae_dos_asientos_del_mismo_pedido():
    # Lote 2 de verdad: AS-00071 (PENDIENTE) y AS-90001 (PAGADA) para PO-2026-0071, mismos datos.
    pendiente = Asiento("AS-00071", "PO-2026-0071", "P010", "B98455101", Decimal("951.89"), date(2026, 5, 24), "PENDIENTE")
    pagado = Asiento("AS-90001", "PO-2026-0071", "P010", "B98455101", Decimal("951.89"), date(2026, 9, 1), "PAGADA")
    otro = Asiento("AS-00096", "PO-2026-0096", "P001", "B46102331", Decimal("3012.89"), date(2026, 1, 8), "PENDIENTE")
    refs = construir_referencias(MaestroEnMemoria([PROV], []), ErpEnMemoria([pagado, otro, pendiente]), [], date(2026, 9, 18), "erp2")
    assert refs.asientos["PO-2026-0071"] == (pendiente, pagado)  # del más antiguo al más reciente
    assert refs.asiento("PO-2026-0071") is pagado and refs.asiento("PO-2026-0096") is otro


def test_decidir_lote_da_un_outcome_por_documento_y_el_ilegible_escala(tmp_path):
    maestro, erp = MaestroEnMemoria([PROV], []), ErpEnMemoria([])
    lecturas = [registro("a.pdf", extraida()), registro("z.pdf"), registro("f.pdf", extraida("f.pdf", pedido="PO-2026-0097", fecha="2027-01-01"))]
    refs = construir_referencias(maestro, erp, lecturas, date(2026, 9, 18), "erp1")
    decisiones = decidir_lote(lecturas, refs, norma_v(tmp_path))
    por = {d.file_id: d for d in decisiones}
    assert set(por) == {"a.pdf", "z.pdf", "f.pdf"}
    assert por["a.pdf"].resultado == "PAGAR" and por["a.pdf"].outcome["version_datos"] == "erp1+memoria"
    assert por["z.pdf"].resultado == "ESCALAR" and "pdf_texto: no pudo" in por["z.pdf"].motivo and por["z.pdf"].metodo == "ninguno"
    assert por["f.pdf"].resultado == "NO_PAGAR" and "futura" in por["f.pdf"].motivo
    r = resumen(decisiones, lecturas)
    assert (r["PAGAR"], r["NO_PAGAR"], r["ESCALAR"], r["leidos"]) == (1, 1, 1, 2)


def test_el_outcome_lleva_el_metodo_de_lectura_real(tmp_path):
    """Un escaneo leído por OCR sale como ocr_determinista en la decisión y en la línea de outcomes, no como texto."""
    lecturas = [registro("scan_001.pdf", extraida("scan_001.pdf", metodo="ocr_determinista"), tipo="escaneado"), registro("a.pdf", extraida())]
    refs = construir_referencias(MaestroEnMemoria([PROV], []), ErpEnMemoria([]), lecturas, date(2026, 9, 18), "erp1")
    por = {d.file_id: d for d in decidir_lote(lecturas, refs, norma_v(tmp_path))}
    assert por["scan_001.pdf"].metodo == "ocr_determinista" and por["scan_001.pdf"].outcome["metodo"] == "ocr_determinista"
    assert por["a.pdf"].metodo == "texto_determinista" and por["a.pdf"].outcome["metodo"] == "texto_determinista"
    assert resumen(list(por.values()), lecturas)["por_metodo"] == {"ocr_determinista": 1, "texto_determinista": 1}


def test_comparar_dice_que_cambia_y_por_que():
    antes = [DecisionGuardada("a.pdf", "PAGAR", "", None, "x", {}), DecisionGuardada("b.pdf", "PAGAR", "", None, "x", {})]
    despues = [DecisionGuardada("a.pdf", "PAGAR", "", None, "x", {}), DecisionGuardada("b.pdf", "NO_PAGAR", "pedido ya pagado", None, "x", {}),
               DecisionGuardada("nuevo.pdf", "PAGAR", "", None, "x", {})]
    cambios = comparar(antes, despues)
    assert [(c.file_id, c.antes, c.despues, c.motivo) for c in cambios] == [("b.pdf", "PAGAR", "NO_PAGAR", "pedido ya pagado")]
