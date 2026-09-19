"""El pipeline de punta a punta sobre documentos de prueba, con DBOS y la base de datos de tests."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from dbos import DBOS

from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.modelos import Asiento
from upistas.infra import django_setup, pipeline
from upistas.puertos import DescargaERP, EstadisticasDescarga

pytestmark = pytest.mark.django_db(transaction=True)


class ClienteFalso:
    def __init__(self, asientos):
        self.asientos = asientos

    def descargar(self):
        return DescargaERP(asientos=self.asientos, lote2_cargado=False, estadisticas=EstadisticasDescarga(peticiones=1))


@pytest.fixture(scope="module")
def dbos_lanzado():
    django_setup.configurar(migrar=False)  # pytest-django ya crea la base de datos de tests
    pipeline.iniciar()
    yield
    DBOS.destroy()


@pytest.fixture
def carpeta(tmp_path):
    def pdf(nombre, texto=None):
        doc = pymupdf.open()
        pagina = doc.new_page()
        if texto:
            pagina.insert_text((72, 72), texto)
        doc.save(tmp_path / nombre)
        doc.close()

    pdf("con_texto.pdf", "FACTURA 2026/0001 Pedido: PO-2026-0001 NIF: B46102331 TOTAL: 121,00")
    pdf("en_blanco.pdf")
    (tmp_path / "no_es_pdf.txt").write_text("hola", encoding="utf-8")
    return tmp_path


def test_reprocesar_el_mismo_lote_no_duplica(dbos_lanzado, tmp_path):
    ruta = tmp_path / "valida.pdf"
    with pymupdf.open() as pdf:
        pagina = pdf.new_page()
        pagina.insert_text((40, 40), "FACTURA FA-001\nNIF B12345678\nIBAN ES1212341234123412341234\nPedido PO-2026-0001\nFecha 15/01/2026\nBase 100,00\nIVA 21% 21,00\nTOTAL 121,00")
        pdf.save(ruta)
    a = pipeline.encolar_lecturas("test", [ruta])[0]
    resultado = a.get_result()
    b = pipeline.encolar_lecturas("test", [ruta])[0]
    assert a.get_workflow_id() == b.get_workflow_id()
    assert resultado == b.get_result()


def test_cli_unificada_con_pdf_excel_y_erp(dbos_lanzado, tmp_path, monkeypatch):
    import argparse
    import json
    from dataclasses import replace
    from datetime import date

    import pymupdf
    from openpyxl import Workbook

    from upistas import cli
    from upistas.infra import contenedor

    original = contenedor.settings
    configuracion = replace(original, outputs_dir=tmp_path / "outputs", hoy=date(2026, 9, 19))
    monkeypatch.setattr(cli, "settings", configuracion)
    monkeypatch.setattr(pipeline, "iniciar", lambda: None)
    carpeta = tmp_path / "facturas"
    carpeta.mkdir()
    with pymupdf.open() as pdf:
        pagina = pdf.new_page()
        pagina.insert_text((40, 40), "FACTURA FA-1001\nProveedor Demo\nNIF B12345678\nIBAN ES1212341234123412341234\nPedido PO-2026-0001\nFecha 15/01/2026\nBase 100,00 EUR\nIVA 21% 21,00 EUR\nTOTAL 121,00 EUR")
        pdf.save(carpeta / "a.pdf")
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Proveedores"
    hoja.append(["ID", "NIF", "IBAN"])
    hoja.append(["P001", "B12345678", "ES1212341234123412341234"])
    hoja = libro.create_sheet("Pedidos_2026")
    hoja.append(["Pedido", "ProveedorID", "Importe_Total", "Estado"])
    hoja.append(["PO-2026-0001", "P001", "121,00", "ABIERTO"])
    excel = tmp_path / "maestro.xlsx"
    libro.save(excel)
    libro.close()
    erp = tmp_path / "erp.json"
    asiento = {"id": "AS-001", "pedido": "PO-2026-0001", "proveedor_id": "P001", "nif": "B12345678", "importe": "121.00", "fecha": "2026-01-15", "estado": "PENDIENTE"}
    erp.write_text(json.dumps([asiento]), encoding="utf-8")
    args = argparse.Namespace(facturas=carpeta, excel=excel, erp_snapshot=erp, ocr=False, lote="cli-unificada", norma="v3", salida="outcomes.jsonl", limit=0)
    try:
        assert cli.cmd_run(args) == 0
        salida = configuracion.outputs_dir / args.salida
        assert json.loads(salida.read_text(encoding="utf-8"))["result"] == "PAGAR"
        (carpeta / "b.pdf").write_bytes((carpeta / "a.pdf").read_bytes())
        assert cli.cmd_run(args) == 0
        assert [json.loads(linea)["result"] for linea in salida.read_text(encoding="utf-8").splitlines()] == ["PAGAR", "NO_PAGAR"]
        erp.write_text(json.dumps([{**asiento, "estado": "PAGADA"}]), encoding="utf-8")
        assert cli.cmd_run(args) == 0
        assert [json.loads(linea)["result"] for linea in salida.read_text(encoding="utf-8").splitlines()] == ["NO_PAGAR", "NO_PAGAR"]
    finally:
        contenedor.configurar(original)


def test_lee_decide_y_guarda_cada_documento(dbos_lanzado, carpeta, monkeypatch):
    from upistas.infra import contenedor
    from upistas.adaptadores.lectores.pdf_texto import LectorPdfTexto
    from upistas.aplicacion.procesar import leer_documento

    monkeypatch.setattr(contenedor, "lectores", lambda: (LectorPdfTexto(),))
    monkeypatch.setattr(pipeline.lectura_acotada, "leer", lambda ruta, configuracion, documento=None:
                        leer_documento(ruta, contenedor.inspector(), contenedor.lectores()))

    monkeypatch.setattr(contenedor, "cliente_erp", lambda: ClienteFalso((
        Asiento("AS-00001", "PO-2026-0001", "P001", "B46102331", Decimal("121.00"), date(2026, 1, 8), "PENDIENTE"),
    )))
    rutas = sorted(p for p in carpeta.iterdir())
    inf = pipeline.procesar_lote("test", rutas, "v3", sincronizar=True)

    por = {d.file_id: d for d in inf.decisiones}
    assert set(por) == {"con_texto.pdf", "en_blanco.pdf", "no_es_pdf.txt"}
    # El lector de texto es todavía un hueco (#23): con texto acaba en ESCALAR explicando por qué.
    assert por["con_texto.pdf"].resultado == "ESCALAR" and "pendiente" in por["con_texto.pdf"].motivo
    assert por["en_blanco.pdf"].resultado == "ESCALAR" and "blanco" in por["en_blanco.pdf"].motivo
    assert inf.ejecucion.estado == "terminada" and inf.ejecucion.version_erp
    assert inf.ejecucion.resumen["documentos"] == 3 and inf.ejecucion.resumen["ESCALAR"] == 3
    assert inf.sincronizacion is not None and inf.sincronizacion.ok

    # Todo queda en la base de datos: documentos, lecturas (también las fallidas) y decisiones.
    from web.panel.models import Decision, Documento, Lectura

    assert Documento.objects.filter(lote="test").count() == 3
    assert Lectura.objects.filter(lote="test").count() == 3 and not Lectura.objects.filter(ok=True).exists()
    assert Decision.objects.filter(ejecucion_id=inf.ejecucion.id).count() == 3


def test_repetir_el_lote_no_relee_y_compara_con_la_pasada_anterior(dbos_lanzado, carpeta, monkeypatch):
    from upistas.infra import contenedor

    asiento = Asiento("AS-00001", "PO-2026-0001", "P001", "B46102331", Decimal("121.00"), date(2026, 1, 8), "PENDIENTE")
    monkeypatch.setattr(contenedor, "cliente_erp", lambda: ClienteFalso((asiento,)))
    rutas = sorted(p for p in carpeta.iterdir())
    primera = pipeline.procesar_lote("test", rutas, "v3")
    segunda = pipeline.procesar_lote("test", rutas, "v3", sincronizar=False)

    assert segunda.anterior is not None and segunda.anterior.id == primera.ejecucion.id
    assert segunda.cambios == []  # mismos datos, misma norma: nada cambia
    assert segunda.ejecucion.version_datos == primera.ejecucion.version_datos

    # Cambia el ERP (el pedido pasa a pagado): nueva versión de datos y la pasada lo registra.
    monkeypatch.setattr(contenedor, "cliente_erp", lambda: ClienteFalso((replace(asiento, estado="PAGADA"),)))
    tercera = pipeline.procesar_lote("test", rutas, "v3")
    assert tercera.ejecucion.version_erp != segunda.ejecucion.version_erp
    assert tercera.sincronizacion.modificados == 1
