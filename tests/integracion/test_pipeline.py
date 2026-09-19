from pathlib import Path

import pytest
from dbos import DBOS

from upistas.infra import pipeline


@pytest.fixture(scope="module")
def dbos_lanzado():
    pipeline.iniciar()
    yield
    DBOS.destroy()


def test_documento_ilegible_acaba_en_escalar(dbos_lanzado):
    h = pipeline.encolar_lote([Path("no_existe/factura_1.txt")], lote="test", version_norma="v3")[0]
    out = h.get_result()
    assert out["file_id"] == "factura_1.txt"
    assert out["result"] == "ESCALAR"


def test_reprocesar_el_mismo_lote_no_duplica(dbos_lanzado):
    a = pipeline.encolar_lote([Path("x/factura_2.txt")], lote="test", version_norma="v3")[0]
    b = pipeline.encolar_lote([Path("x/factura_2.txt")], lote="test", version_norma="v3")[0]
    assert a.get_workflow_id() == b.get_workflow_id()
    assert a.get_result() == b.get_result()


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
        assert [json.loads(linea)["result"] for linea in salida.read_text(encoding="utf-8").splitlines()] == ["ESCALAR", "ESCALAR"]
        erp.write_text(json.dumps([{**asiento, "estado": "PAGADA"}]), encoding="utf-8")
        assert cli.cmd_run(args) == 0
        assert [json.loads(linea)["result"] for linea in salida.read_text(encoding="utf-8").splitlines()] == ["NO_PAGAR", "NO_PAGAR"]
    finally:
        contenedor.configurar(original)
