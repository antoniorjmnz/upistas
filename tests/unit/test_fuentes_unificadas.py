import json
from dataclasses import replace
from decimal import Decimal

import pytest
from openpyxl import Workbook

from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.adaptadores.fuentes.snapshot import ErpSnapshot


def crear_excel(ruta, iban_alternativo=None, importe="121,00"):
    libro = Workbook()
    proveedores = libro.active
    proveedores.title = "Proveedores"
    proveedores.append([" ID ", "Razon Social", "NIF", "IBAN"])
    proveedores.append(["P001", " Demo ", "B12345678", "ES12 1234 1234 1234 1234 1234"])
    proveedores.append(["P001", "Demo", "B12345678", iban_alternativo or "ES1212341234123412341234"])
    pedidos = libro.create_sheet("Pedidos_2026")
    pedidos.append(["Pedido", "ProveedorID", "NIF", "Importe_Total", "Estado"])
    pedidos.append(["PO-2026-0001", "P001", "B12345678", importe, "ABIERTO"])
    libro.save(ruta)
    libro.close()


def test_excel_deduplica_identicos_y_normaliza(tmp_path):
    ruta = tmp_path / "maestro.xlsx"
    crear_excel(ruta)
    fuente = MaestroExcel(ruta)
    assert len(fuente.proveedores()) == 1
    assert fuente.proveedores()[0].iban == "ES1212341234123412341234"
    assert fuente.pedidos()[0].importe == Decimal("121.00")
    assert fuente.pedidos()[0].estado == "ABIERTO"


@pytest.mark.parametrize("importe", [859.4, 2383.2, 121, 0.01, 100.005])
def test_importe_numerico_excel_no_se_reinterpreta_como_texto(tmp_path, importe):
    ruta = tmp_path / "maestro.xlsx"
    crear_excel(ruta, importe=importe)
    assert MaestroExcel(ruta).pedidos()[0].importe == Decimal(str(importe))


def test_excel_no_oculta_maestro_contradictorio(tmp_path):
    ruta = tmp_path / "maestro.xlsx"
    crear_excel(ruta, "ES0000000000000000000000")
    with pytest.raises(ValueError, match="contradictorio"):
        MaestroExcel(ruta).proveedores()


def test_snapshot_erp_usa_estado_real(tmp_path):
    ruta = tmp_path / "erp.json"
    ruta.write_text(json.dumps([{
        "id": "AS-001", "pedido": "PO-2026-0001", "proveedor_id": "P001",
        "nif": "B12345678", "importe": "121.00", "fecha": "2026-01-15", "estado": "PAGADA",
    }]), encoding="utf-8")
    assert ErpSnapshot(ruta).asientos()[0].estado == "PAGADA"


def test_snapshot_ambiguo_no_sobrescribe_asiento(tmp_path):
    ruta = tmp_path / "erp.json"
    asiento = {"id": "AS-001", "pedido": "PO-2026-0001", "proveedor_id": "P001", "nif": "B12345678", "importe": "121", "fecha": "2026-01-15", "estado": "PENDIENTE"}
    ruta.write_text(json.dumps([asiento, {**asiento, "id": "AS-002", "estado": "PAGADA"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="repetido"):
        ErpSnapshot(ruta).asientos()


@pytest.fixture
def autodeteccion(tmp_path, monkeypatch):
    from upistas.infra import contenedor

    original = contenedor.settings
    contenedor.configurar(replace(original, excel_path=None, caja_dir=tmp_path / "caja"))
    rutas = [tmp_path / "src" / "upistas" / "FINAL_v7_DEFINITIVO_ahorasi.xlsx"]
    rutas[0].parent.mkdir(parents=True)
    crear_excel(rutas[0])
    monkeypatch.setattr(contenedor, "rutas_maestro", lambda: rutas, raising=False)
    yield contenedor, rutas
    contenedor.configurar(original)


def test_detecta_el_excel_de_src_sin_indicar_ruta(autodeteccion):
    contenedor, rutas = autodeteccion
    fuente = contenedor.maestro()
    assert isinstance(fuente, MaestroExcel)
    assert fuente.ruta == rutas[0]
    assert len(contenedor.referencias().proveedores) == 1
    assert len(contenedor.referencias().pedidos) == 1


def test_no_elige_arbitrariamente_entre_dos_excels(autodeteccion):
    contenedor, rutas = autodeteccion
    otra = rutas[0].parent / "otro.xlsx"
    crear_excel(otra)
    rutas.append(otra)
    with pytest.raises(ValueError, match="--excel"):
        contenedor.maestro()


def test_ruta_explicita_prevalece_sobre_autodeteccion(autodeteccion):
    contenedor, rutas = autodeteccion
    otra = rutas[0].parent / "otro.xlsx"
    crear_excel(otra, importe=859.4)
    contenedor.configurar(replace(contenedor.settings, excel_path=otra))
    assert contenedor.maestro().ruta == otra
    assert contenedor.maestro().pedidos()[0].importe == Decimal("859.4")
