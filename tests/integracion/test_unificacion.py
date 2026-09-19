import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pymupdf
import pytest
from openpyxl import Workbook

from upistas.aplicacion.lote import consolidar_lote
from upistas.aplicacion.mapeo import a_outcome
from upistas.aplicacion.procesar import decidir, leer_documento
from upistas.infra import contenedor


@pytest.fixture
def entorno(tmp_path):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Proveedores"
    hoja.append(["ID", "Razon Social", "NIF", "IBAN"])
    hoja.append(["P001", "Demo", "B12345678", "ES1212341234123412341234"])
    hoja = libro.create_sheet("Pedidos_2026")
    hoja.append(["Pedido", "ProveedorID", "Importe_Total", "Estado"])
    hoja.append(["PO-2026-0001", "P001", "121,00", "ABIERTO"])
    excel = tmp_path / "maestro.xlsx"
    libro.save(excel)
    libro.close()
    erp = tmp_path / "erp.json"
    erp.write_text(json.dumps([{
        "id": "AS-001", "pedido": "PO-2026-0001", "proveedor_id": "P001", "nif": "B12345678",
        "importe": "121.00", "fecha": "2026-01-15", "estado": "PENDIENTE",
    }]), encoding="utf-8")
    original = contenedor.settings
    contenedor.configurar(replace(original, excel_path=excel, erp_snapshot=erp, usar_ocr=False, outputs_dir=tmp_path, hoy=date(2026, 9, 19)))
    yield tmp_path
    contenedor.configurar(original)


def documento(ruta: Path):
    with pymupdf.open() as pdf:
        pagina = pdf.new_page()
        pagina.insert_text((40, 40), "FACTURA FA-1001\nProveedor Demo\nNIF B12345678\nIBAN ES1212341234123412341234\nPedido PO-2026-0001\nFecha 15/01/2026\nBase imponible 100,00 EUR\nIVA 21% 21,00 EUR\nTOTAL 121,00 EUR")
        pdf.save(ruta)
    return ruta


def procesar(ruta):
    lectura = leer_documento(ruta, contenedor.inspector(), contenedor.lectores())
    return a_outcome(decidir(ruta.name, lectura, contenedor.referencias(), contenedor.norma("v3")))


def test_pdf_a_outcome_con_ambos_enfoques(entorno):
    resultado = procesar(documento(entorno / "a.pdf"))
    assert resultado["result"] == "PAGAR"
    assert len(resultado["reglas"]) == 6
    assert list((entorno / "extracciones").glob("*.json"))


def test_dos_facturas_del_mismo_pedido_no_se_aprueban(entorno):
    resultados = [procesar(documento(entorno / nombre)) for nombre in ("a.pdf", "b.pdf")]
    assert all(r["result"] == "PAGAR" for r in resultados)
    consolidados = consolidar_lote(resultados)
    assert all(r["result"] == "ESCALAR" for r in consolidados)
    assert all("duplicado" in r["motivo"].lower() for r in consolidados)
    assert consolidar_lote(list(reversed(resultados))) == list(reversed(consolidados))


def test_duplicado_no_rebaja_un_no_pagar():
    resultados = [
        {"file_id": "a.pdf", "result": "NO_PAGAR", "pedido": "PO-1", "motivo": "Pagada", "norma": "v3", "reglas": []},
        {"file_id": "b.pdf", "result": "PAGAR", "pedido": "PO-1", "motivo": "Cumple", "norma": "v3", "reglas": []},
    ]
    assert consolidar_lote(resultados)[0]["result"] == "NO_PAGAR"


def test_cambio_de_referencias_invalida_identidad_de_ejecucion(entorno):
    anterior = contenedor.huella("v3")
    contenedor.configurar(replace(contenedor.settings, hoy=date(2026, 9, 20)))
    assert contenedor.huella("v3") != anterior
