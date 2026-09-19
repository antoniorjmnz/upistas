import argparse
import io
import json
from dataclasses import replace
from functools import cache
from types import SimpleNamespace

import pymupdf
import pytest

from upistas import cli
from upistas.infra import contenedor, pipeline


@pytest.fixture
def opciones(tmp_path, monkeypatch):
    original = contenedor.settings
    configuracion = replace(cli.settings, caja_dir=tmp_path / "sin_caja", excel_path=None, erp_snapshot=None, usar_ocr=False, outputs_dir=tmp_path / "outputs")
    monkeypatch.setattr(cli, "settings", configuracion)
    carpeta = tmp_path / "facturas"
    carpeta.mkdir()
    with pymupdf.open() as pdf:
        pagina = pdf.new_page()
        pagina.insert_text((40, 40), "FACTURA FA-1001\nProveedor Demo SL\nNIF B12345678\nFecha 01/01/2026\nPedido PO-2026-0001\nIBAN ES1212341234123412341234\nBase imponible....100,00\nIVA (21%)....21,00\nTOTAL....121,00")
        pdf.save(carpeta / "a.pdf")
    yield argparse.Namespace(facturas=carpeta, excel=None, erp_snapshot=None, ocr=False, lote="test-cli", norma="v3", salida="prueba.jsonl", limit=10)
    contenedor.configurar(original)


def test_run_sin_fuentes_no_emite_decisiones_enganosas(opciones, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "iniciar", lambda: pytest.fail("No debe iniciar una auditoría sin fuentes"))
    assert cli.cmd_run(opciones) == 2
    assert not (cli.settings.outputs_dir / opciones.salida).exists()
    assert "extract" in capsys.readouterr().err


def test_run_sin_erp_no_emite_decisiones(opciones, monkeypatch, capsys):
    monkeypatch.setattr(contenedor, "referencias", cache(lambda: SimpleNamespace(proveedores={"B12345678": object()}, asientos={})))
    monkeypatch.setattr(pipeline, "iniciar", lambda: pytest.fail("No debe iniciar una auditoría sin ERP"))
    assert cli.cmd_run(opciones) == 2
    assert "ERP" in capsys.readouterr().err


def test_resumen_compatible_con_consola_windows(opciones, monkeypatch):
    referencias = SimpleNamespace(proveedores={"B12345678": object()}, asientos={"PO-2026-0001": object()})
    monkeypatch.setattr(contenedor, "referencias", cache(lambda: referencias))
    monkeypatch.setattr(pipeline, "iniciar", lambda: None)
    resultado = {"file_id": "a.pdf", "result": "PAGAR", "motivo": "Cumple", "norma": "v3", "reglas": []}
    monkeypatch.setattr(pipeline, "encolar_lote", lambda *args: [SimpleNamespace(get_result=lambda: resultado)])
    buffer = io.BytesIO()
    consola = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr(cli.sys, "stdout", consola)
    assert cli.cmd_run(opciones) == 0
    consola.flush()
    assert "1 facturas" in buffer.getvalue().decode("cp1252")


def test_extraer_sin_fuentes_muestra_campos_y_no_clasifica(opciones):
    assert cli.cmd_extract(opciones) == 0
    fila = json.loads((cli.settings.outputs_dir / opciones.salida).read_text(encoding="utf-8"))
    assert fila["file_id"] == "a.pdf"
    assert "result" not in fila
    assert fila["extraccion"]["campos"]["nif"]["valor"] == "B12345678"
    assert fila["extraccion"]["campos"]["total"]["valor"] == 121


def test_extraer_pdf_roto_conserva_su_error_y_continua(opciones):
    (opciones.facturas / "b.pdf").write_bytes(b"pdf roto")
    assert cli.cmd_extract(opciones) == 0
    filas = [json.loads(linea) for linea in (cli.settings.outputs_dir / opciones.salida).read_text(encoding="utf-8").splitlines()]
    assert len(filas) == 2
    assert filas[1]["extraccion"] is None
    assert filas[1]["errores"]
