"""Los CSV de altas de La Caja: mismas columnas que el Excel, cabeceras a su manera."""
from datetime import date
from decimal import Decimal

import pytest

from upistas.adaptadores.fuentes.csv_altas import AltasCSV
from upistas.config import settings

CAJA = settings.caja_dir

PROVEEDORES = (
    "ID,Razon Social,NIF,IBAN,Ciudad,Condiciones\n"
    "P012,Müller & Partner GmbH,DE812345678,DE89 3704 0044 0532 0130 00,Hamburg,30 dias\n"
    "P013,  Consulting Méridional SARL ,FR40303265045,fr76 3000 4000 3000 0000 1234 567,Marseille,45 dias\n"
    "\n"
)
PEDIDOS = (
    "pedido,proveedor_id,nif,importe_total,estado,fecha_pedido\n"
    "PO-2026-0500,P002,A41220987,3139.66,ABIERTO,2026-08-17\n"
    "PO-2026-0601,P012,DE812345678,\"1.234,50\",ABIERTO,17/08/2026\n"
    "PO-2026-0601,P012,DE812345678,999.00,ABIERTO,2026-08-18\n"
    "PO-2026-0602,P013,FR40303265045,,ABIERTO,2026-08-19\n"
    "no es un pedido,P013,,10.00,ABIERTO,\n"
)


@pytest.fixture
def altas(tmp_path):
    (tmp_path / "proveedores.csv").write_text(PROVEEDORES, encoding="utf-8")
    (tmp_path / "pedidos.csv").write_text(PEDIDOS, encoding="utf-8")
    return AltasCSV((tmp_path / "proveedores.csv",), (tmp_path / "pedidos.csv",))


def test_los_proveedores_salen_limpios_como_del_excel(altas):
    provs = {p.id: p for p in altas.proveedores()}
    assert set(provs) == {"P012", "P013"}
    assert provs["P012"].iban == "DE89370400440532013000" and provs["P012"].condiciones_dias == 30
    assert provs["P013"].nombre == "Consulting Méridional SARL" and provs["P013"].iban.startswith("FR76")
    assert any("P012 con NIF raro" in a for a in altas.avisos)


def test_los_pedidos_entienden_proveedor_id_con_guion_bajo_y_los_importes_a_la_espanola(altas):
    pedidos = {p.id: p for p in altas.pedidos()}
    assert set(pedidos) == {"PO-2026-0500", "PO-2026-0601"}
    assert pedidos["PO-2026-0500"].proveedor_id == "P002" and pedidos["PO-2026-0500"].fecha == date(2026, 8, 17)
    assert pedidos["PO-2026-0601"].importe == Decimal("1234.50") and pedidos["PO-2026-0601"].fecha == date(2026, 8, 17)
    assert pedidos["PO-2026-0601"].estado == "ABIERTO"
    assert any("PO-2026-0601 repetido" in a for a in altas.avisos)
    assert any("PO-2026-0602 sin importe" in a for a in altas.avisos)


def test_no_trae_marcas_de_revisar_y_tiene_version(altas, tmp_path):
    assert altas.marcados_para_revisar() == frozenset()
    version = altas.version
    assert len(version) == 12
    (tmp_path / "pedidos.csv").write_text(PEDIDOS + "PO-2026-0603,P012,,5.00,ABIERTO,2026-08-20\n", encoding="utf-8")
    assert AltasCSV((tmp_path / "proveedores.csv",), (tmp_path / "pedidos.csv",)).version != version


def test_acepta_punto_y_coma_bom_y_cabeceras_del_excel(tmp_path):
    ruta = tmp_path / "pedidos_excel.csv"
    ruta.write_bytes("﻿Pedido;ProveedorID;NIF;Importe_Total;Estado;Fecha_Pedido\nPO-2026-0700;P001;B46102331;2490,00;ABIERTO;2026-09-01\n".encode("utf-8"))
    pedidos = AltasCSV(rutas_pedidos=(ruta,)).pedidos()
    assert len(pedidos) == 1
    assert pedidos[0].proveedor_id == "P001" and pedidos[0].importe == Decimal("2490.00")


def test_acepta_un_csv_guardado_desde_windows(tmp_path):
    ruta = tmp_path / "proveedores_ansi.csv"
    ruta.write_bytes("ID;Razon Social;NIF;IBAN;Ciudad;Condiciones\nP020;Cerámicas Aragón S.L.;B50123456;ES21 0049 1500 0512 3456 7890;Zaragoza;60 dias\n".encode("cp1252"))
    provs = AltasCSV(rutas_proveedores=(ruta,)).proveedores()
    assert len(provs) == 1 and provs[0].nombre == "Cerámicas Aragón S.L." and provs[0].condiciones_dias == 60


def test_avisa_si_el_fichero_no_tiene_las_columnas_o_esta_vacio(tmp_path):
    (tmp_path / "raro.csv").write_text("nombre,telefono\nPepe,600000000\n", encoding="utf-8")
    (tmp_path / "vacio.csv").write_text("", encoding="utf-8")
    altas = AltasCSV((tmp_path / "raro.csv",), (tmp_path / "vacio.csv",))
    assert altas.proveedores() == [] and altas.pedidos() == []
    assert any("raro.csv: no tiene las columnas esperadas" in a for a in altas.avisos)
    assert any("vacio.csv: está vacío" in a for a in altas.avisos)


def test_varios_ficheros_se_leen_seguidos(tmp_path):
    (tmp_path / "a.csv").write_text("pedido,proveedor_id,nif,importe_total,estado,fecha_pedido\nPO-2026-0801,P001,,10.00,ABIERTO,2026-09-01\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("pedido,proveedor_id,nif,importe_total,estado,fecha_pedido\nPO-2026-0802,P001,,20.00,ABIERTO,2026-09-02\n", encoding="utf-8")
    pedidos = AltasCSV(rutas_pedidos=(tmp_path / "a.csv", tmp_path / "b.csv")).pedidos()
    assert [p.id for p in pedidos] == ["PO-2026-0801", "PO-2026-0802"]


@pytest.mark.skipif(not (CAJA / "pedidos_nuevos.csv").exists(), reason="La Caja no está clonada")
def test_las_altas_de_verdad_del_lote_2():
    altas = AltasCSV((CAJA / "proveedores_nuevos.csv",), (CAJA / "pedidos_nuevos.csv",))
    provs = {p.id: p for p in altas.proveedores()}
    pedidos = altas.pedidos()
    assert set(provs) == {"P012", "P013", "P014", "P015"}
    assert provs["P014"].nombre == "Serviços Aljarafe Ltda" and provs["P013"].condiciones_dias == 45
    assert len(pedidos) == 39 and {p.proveedor_id for p in pedidos} >= {"P012", "P013", "P014", "P015"}
    assert all(p.importe > 0 and p.fecha is not None for p in pedidos)
