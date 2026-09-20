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
    monkeypatch.setattr(contenedor, "maestro", cache(lambda: SimpleNamespace(proveedores=lambda: [object()])))
    monkeypatch.setattr(pipeline, "iniciar", lambda: None)

    def sin_erp(*args, **kwargs):
        raise RuntimeError("No hay ninguna copia del ERP")

    monkeypatch.setattr(pipeline, "procesar_lote", sin_erp)
    assert cli.cmd_run(opciones) == 2
    assert "ERP" in capsys.readouterr().err


RESULTADO = {"file_id": "a.pdf", "result": "PAGAR", "motivo": "Cumple", "norma": "v3", "reglas": []}


def _lote_de_una_factura(monkeypatch):
    """El pipeline de mentira: maestro con un proveedor y un lote ya decidido con una factura que se paga."""
    monkeypatch.setattr(contenedor, "maestro", cache(lambda: SimpleNamespace(proveedores=lambda: [object()])))
    monkeypatch.setattr(pipeline, "iniciar", lambda: None)
    informe = SimpleNamespace(
        sincronizacion=None, avisos=[], leidos_ahora=1, desde_cache=0, anterior=None,
        segundos_lectura=0.1, segundos_decision=0.01,
        ejecucion=SimpleNamespace(id=1, version_erp="erp", version_excel="excel", resumen={
            "PAGAR": 1, "NO_PAGAR": 0, "ESCALAR": 0, "tokens_in": 0, "coste_eur": 0,
        }),
        decisiones=[SimpleNamespace(file_id="a.pdf", resultado="PAGAR", motivo="Cumple", alertas=(), outcome=RESULTADO)],
    )
    monkeypatch.setattr(pipeline, "procesar_lote", lambda *args, **kwargs: informe)


def test_el_informe_se_llama_como_el_fichero_de_la_entrega():
    assert cli.nombre_outcomes("lote1") == "outcomes.jsonl"
    assert cli.nombre_outcomes("lote2") == "outcomes_lote2.jsonl"


def test_run_guarda_el_informe_aunque_no_se_pida_salida(opciones, monkeypatch):
    _lote_de_una_factura(monkeypatch)
    opciones.salida = None
    opciones.lote = "lote2"
    assert cli.cmd_run(opciones) == 0
    lineas = (cli.settings.outputs_dir / "outcomes_lote2.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(linea) for linea in lineas] == [RESULTADO]
    assert not (cli.settings.outputs_dir / "outcomes.jsonl").exists()


def test_salida_cambia_el_nombre_del_informe(opciones, monkeypatch):
    _lote_de_una_factura(monkeypatch)
    assert cli.cmd_run(opciones) == 0
    assert (cli.settings.outputs_dir / "prueba.jsonl").exists()
    assert not (cli.settings.outputs_dir / "outcomes_test-cli.jsonl").exists()


def test_resumen_compatible_con_consola_windows(opciones, monkeypatch):
    _lote_de_una_factura(monkeypatch)
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


def test_timeout_de_lectura_se_registra_sin_bloquear_la_extraccion(opciones, monkeypatch):
    import subprocess
    from upistas.infra import lectura_acotada

    opciones.timeout_lectura = 0.01

    def agotar_tiempo(comando, **kwargs):
        assert kwargs["timeout"] == opciones.timeout_lectura
        raise subprocess.TimeoutExpired(comando, kwargs["timeout"])

    monkeypatch.setattr(lectura_acotada.subprocess, "run", agotar_tiempo)
    assert cli.cmd_extract(opciones) == 0
    fila = json.loads((cli.settings.outputs_dir / opciones.salida).read_text(encoding="utf-8"))
    assert fila["extraccion"] is None
    assert "Tiempo de lectura agotado" in fila["errores"][0]
