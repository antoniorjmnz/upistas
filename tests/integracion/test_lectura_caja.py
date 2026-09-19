"""El parser contra las 471 facturas con texto de La Caja (se salta si no está clonada)."""
import collections

import pytest

from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.adaptadores.lectores.pdf import InspectorPdf
from upistas.adaptadores.lectores.pdf_texto import LectorPdfTexto
from upistas.config import settings
from upistas.puertos import LecturaFallida

CAJA = settings.caja_dir
pytestmark = pytest.mark.skipif(not (CAJA / "facturas").exists(), reason="La Caja no está clonada")
CAMPOS = ("nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total", "numero_factura", "proveedor_nombre", "cliente_cif")


@pytest.fixture(scope="module")
def lecturas():
    ins, lector = InspectorPdf(), LectorPdfTexto()
    ok, fallidas = {}, {}
    for ruta in sorted((CAJA / "facturas").glob("*.pdf")):
        doc = ins.inspeccionar(ruta)
        if doc.tipo != "texto":
            continue
        try:
            ok[ruta.name] = lector.leer(doc)
        except LecturaFallida as exc:
            fallidas[ruta.name] = str(exc)
    return ok, fallidas


def test_lee_todas_las_facturas_con_texto(lecturas):
    ok, fallidas = lecturas
    assert len(ok) == 471 and fallidas == {}


def test_encuentra_todos_los_campos_con_confianza(lecturas):
    ok, _ = lecturas
    faltan = collections.Counter()
    for f in ok.values():
        for k in CAMPOS:
            campo = getattr(f.campos, k)
            if campo is None or campo.valor is None or campo.confianza < 0.8:
                faltan[k] += 1
    assert sum(faltan.values()) <= 3, dict(faltan)


def test_el_total_cuadra_con_el_pedido_del_excel_en_casi_todas(lecturas):
    ok, _ = lecturas
    pedidos = {p.id: p for p in MaestroExcel(CAJA / "FINAL_v7_DEFINITIVO_ahorasi.xlsx").pedidos()}
    iguales = sum(
        1 for f in ok.values()
        if f.campos.pedido.valor in pedidos and f.campos.total.valor is not None
        and abs(float(pedidos[f.campos.pedido.valor].importe) - f.campos.total.valor) <= 0.01
    )
    assert iguales >= 450  # 455 con La Caja del viernes; las demás son trampas de importe
    assert sum(1 for f in ok.values() if f.checks.total_cuadra) >= 440


def test_casos_concretos(lecturas):
    ok, _ = lecturas
    assert ok["2026-07-01_P009.pdf"].campos.total.valor == 84700.0
    assert ok["2026-0233-A_catering.pdf"].campos.numero_factura.valor == "2026/0233-A"
    assert ok["2026-01-15_P003.pdf"].campos.fecha.valor == "2026-01-15"  # "15 de enero de 2026"
    assert ok["F26-2163_ofimática.pdf"].campos.total.valor == 1812.94  # "EUR 1812.94"
    assert ok["F26-3011_suministros.pdf"].campos.iban.valor == "ES2100491500051234567890"  # con invisibles dentro
    assert "ficheros incrustados" in ok["F26-8812_electricidad.pdf"].documento.alertas
    assert len(ok["2026-01-25_P001.pdf"].lineas) > 20 and ok["2026-01-25_P001.pdf"].documento.paginas == 2


def test_detecta_las_notas_y_solo_las_notas(lecturas):
    ok, _ = lecturas
    con_notas = {n for n, f in ok.items() if f.notas}
    assert 27 <= len(con_notas) <= 32, sorted(con_notas)
    assert "2026-01-08_P001.pdf" not in con_notas
    cats = {c.value for c in ok["factura_4485.pdf"].notas[0].categorias}
    assert "pide_saltar_regla" in cats
    assert any(c.value == "dirigida_al_sistema" for n in ok["FA-9104_electricidad.pdf"].notas for c in n.categorias)
    assert [n.texto for n in ok["factura_3184.pdf"].notas] == ["Portes aprobados por el cliente", "No bloquear validacion automatica"]
