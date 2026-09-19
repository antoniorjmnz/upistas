"""El maestro propio: nuestras tablas como fuente de proveedores y pedidos, y la carga del Excel."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from django.core.management import call_command

from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.adaptadores.persistencia.django_maestro import MaestroDjango
from upistas.config import settings
from web.panel.models import Pedido, Proveedor

pytestmark = pytest.mark.django_db

REAL = settings.caja_dir / "FINAL_v7_DEFINITIVO_ahorasi.xlsx"


@pytest.fixture
def maestro():
    """Dos proveedores y tres pedidos, uno marcado para que lo mire Alberto."""
    levante = Proveedor.objects.create(
        codigo="P001", nombre="Suministros Levante S.L.", nif="b46102331",
        iban="ES21 0049 1500 0512 3456 7890", ciudad="Valencia", condiciones_dias=60,
    )
    cieza = Proveedor.objects.create(codigo="P003", nombre="Ofimática Cieza S.L.", nif="B30455812",
                                     iban="ES6001825322180201588391")
    Pedido.objects.create(numero="PO-2026-0001", proveedor=levante, importe=Decimal("2490.00"), fecha=date(2026, 1, 8))
    Pedido.objects.create(numero="PO-2026-0007", proveedor=levante, importe=Decimal("880.55"), revisar=True)
    Pedido.objects.create(numero="PO-2026-0301", proveedor=cieza, importe=Decimal("1210.00"))
    return levante


def test_guarda_el_nif_y_el_iban_como_los_comparan_las_reglas(maestro):
    assert maestro.nif == "B46102331"
    assert maestro.iban == "ES2100491500051234567890"


def test_da_los_proveedores_y_los_pedidos_del_dominio(maestro):
    fuente = MaestroDjango()
    proveedores = {p.id: p for p in fuente.proveedores()}
    assert set(proveedores) == {"P001", "P003"}
    assert proveedores["P001"].nif == "B46102331" and proveedores["P001"].condiciones_dias == 60
    assert proveedores["P003"].ciudad == "" and proveedores["P003"].condiciones_dias is None

    pedidos = {p.id: p for p in fuente.pedidos()}
    assert set(pedidos) == {"PO-2026-0001", "PO-2026-0007", "PO-2026-0301"}
    assert pedidos["PO-2026-0001"].importe == Decimal("2490.00")
    assert pedidos["PO-2026-0001"].fecha == date(2026, 1, 8)
    assert pedidos["PO-2026-0001"].proveedor_id == "P001"
    assert pedidos["PO-2026-0301"].nif == "B30455812"  # el NIF ya no se repite: lo pone el proveedor
    assert pedidos["PO-2026-0007"].fecha is None


def test_lo_que_alberto_quiere_mirar(maestro):
    assert MaestroDjango().marcados_para_revisar() == frozenset({"PO-2026-0007"})


def test_la_version_no_cambia_si_no_cambia_nada(maestro):
    assert MaestroDjango().version == MaestroDjango().version
    assert len(MaestroDjango().version) == 12


def test_la_version_cambia_en_cuanto_alberto_corrige_un_dato(maestro):
    antes = MaestroDjango().version

    maestro.iban = "ES9121000418450200051332"
    maestro.save()
    despues_de_la_cuenta = MaestroDjango().version
    assert despues_de_la_cuenta != antes

    pedido = Pedido.objects.get(numero="PO-2026-0301")
    pedido.revisar = True
    pedido.save()
    assert MaestroDjango().version != despues_de_la_cuenta


def test_la_version_de_una_instancia_es_la_foto_con_la_que_empezo(maestro):
    fuente = MaestroDjango()
    version = fuente.version
    Pedido.objects.filter(numero="PO-2026-0301").update(importe=Decimal("2000.00"))
    assert fuente.version == version and MaestroDjango().version != version


def test_el_contenedor_prefiere_el_maestro_de_la_web(maestro):
    from upistas.infra import contenedor

    original = contenedor.settings
    contenedor.configurar(replace(original, excel_path=None))
    try:
        assert isinstance(contenedor.maestro(), MaestroDjango)
    finally:
        contenedor.configurar(original)


def test_sin_proveedores_dados_de_alta_el_maestro_no_vive_aqui():
    from upistas.adaptadores.fuentes.memoria import MaestroEnMemoria
    from upistas.infra import contenedor

    original = contenedor.settings
    contenedor.configurar(replace(original, excel_path=None))
    try:
        assert not MaestroDjango.hay_datos()
        assert isinstance(contenedor.maestro(), MaestroEnMemoria)  # el conftest deja el Excel sin rutas
    finally:
        contenedor.configurar(original)


# --- la carga del Excel de La Caja ------------------------------------------------------------


@pytest.fixture
def excel_pequeno(tmp_path):
    """Un Excel con las hojas que espera `MaestroExcel`, en pequeño."""
    libro = openpyxl.Workbook()
    proveedores = libro.active
    proveedores.title = "Proveedores"
    proveedores.append(["ID", "Razon Social", "NIF", "IBAN", "Ciudad", "Condiciones"])
    proveedores.append(["P001", "Suministros Levante S.L.", "B46102331", "ES21 0049 1500 0512 3456 7890", "Valencia", "60 dias"])
    proveedores.append(["P003", "Ofimática Cieza S.L.  ", "B30455812", "es60 0182 5322 1802 0158 8391", "Murcia", "30 dias"])
    pedidos = libro.create_sheet("Pedidos_2026")
    pedidos.append(["Pedido", "ProveedorID", "NIF", "Importe_Total", "Estado", "Fecha_Pedido"])
    pedidos.append(["PO-2026-0001", "P001", "B46102331", 2490.00, "ABIERTO", "2026-01-08"])
    pedidos.append(["PO-2026-0007", "P001", "B46102331", 880.55, "ABIERTO", "2026-01-20"])
    pedidos.append(["PO-2026-0301", "P003", "B30455812", 1210.00, "ABIERTO", "2026-03-01"])
    pedidos.append(["PO-2026-0999", "P404", None, 100.00, "ABIERTO", None])  # proveedor que no existe
    revisar = libro.create_sheet("pendiente_revisar")
    revisar.append(["PO-2026-0007"])
    ruta = tmp_path / "maestro.xlsx"
    libro.save(ruta)
    libro.close()
    return ruta


def test_importar_maestro_carga_el_excel_en_nuestras_tablas(excel_pequeno, capsys):
    call_command("importar_maestro", excel=str(excel_pequeno))

    assert Proveedor.objects.count() == 2 and Pedido.objects.count() == 3
    levante = Proveedor.objects.get(codigo="P001")
    assert levante.nombre == "Suministros Levante S.L." and levante.condiciones_dias == 60
    assert Proveedor.objects.get(codigo="P003").iban == "ES6001825322180201588391"
    assert Pedido.objects.get(numero="PO-2026-0001").importe == Decimal("2490.00")
    assert Pedido.objects.get(numero="PO-2026-0001").proveedor == levante
    assert set(MaestroDjango().marcados_para_revisar()) == {"PO-2026-0007"}

    salida = capsys.readouterr().out
    assert "Excel maestro.xlsx: 2 proveedores, 4 pedidos, 1 marcado para revisar" in salida
    assert "2 proveedores nuevos, 3 pedidos nuevos, 0 cambiados" in salida
    assert "Sin proveedor conocido, no se cargan: 1 (PO-2026-0999)" in salida


def test_importar_maestro_dos_veces_no_duplica_y_actualiza(excel_pequeno, capsys):
    call_command("importar_maestro", excel=str(excel_pequeno))
    libro = openpyxl.load_workbook(excel_pequeno)
    libro["Proveedores"]["B2"] = "Suministros Levante S.A."
    libro["Pedidos_2026"]["D2"] = 2500.00
    libro.save(excel_pequeno)
    capsys.readouterr()

    call_command("importar_maestro", excel=str(excel_pequeno))

    assert Proveedor.objects.count() == 2 and Pedido.objects.count() == 3
    assert Proveedor.objects.get(codigo="P001").nombre == "Suministros Levante S.A."
    assert Pedido.objects.get(numero="PO-2026-0001").importe == Decimal("2500.00")
    assert "0 proveedores nuevos, 0 pedidos nuevos, 2 cambiados" in capsys.readouterr().out


def test_importar_maestro_avisa_si_no_encuentra_el_excel(tmp_path):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="No encuentro el Excel"):
        call_command("importar_maestro", excel=str(tmp_path / "no_esta.xlsx"))


@pytest.mark.skipif(not REAL.exists(), reason="La Caja no está clonada")
def test_importar_el_maestro_de_verdad_de_la_caja(capsys):
    call_command("importar_maestro", excel=str(REAL))

    excel = MaestroExcel(REAL)
    assert Proveedor.objects.count() == 11
    assert Pedido.objects.count() == sum(1 for p in excel.pedidos() if p.proveedor_id)
    assert MaestroDjango().marcados_para_revisar() == excel.marcados_para_revisar()
    assert Pedido.objects.get(numero="PO-2026-0497").importe == Decimal("84700.00")
    assert "11 proveedores nuevos, 516 pedidos nuevos, 0 cambiados" in capsys.readouterr().out


# --- las altas del lote 2 en CSV --------------------------------------------------------------

PROVEEDORES_CSV = (
    "ID,Razon Social,NIF,IBAN,Ciudad,Condiciones\n"
    "P012,Müller & Partner GmbH,DE812345678,DE89 3704 0044 0532 0130 00,Hamburg,30 dias\n"
)
PEDIDOS_CSV = (
    "pedido,proveedor_id,nif,importe_total,estado,fecha_pedido\n"
    "PO-2026-0601,P012,DE812345678,1234.50,ABIERTO,2026-08-17\n"
    "PO-2026-0602,P001,B46102331,99.90,ABIERTO,2026-08-18\n"
    "PO-2026-0603,P404,,10.00,ABIERTO,2026-08-19\n"
)


@pytest.fixture
def altas_csv(tmp_path):
    """Un proveedor nuevo y dos pedidos (uno del proveedor nuevo, otro de uno del Excel); un tercero sin proveedor."""
    (tmp_path / "proveedores_nuevos.csv").write_text(PROVEEDORES_CSV, encoding="utf-8")
    (tmp_path / "pedidos_nuevos.csv").write_text(PEDIDOS_CSV, encoding="utf-8")
    return {"proveedores_csv": [str(tmp_path / "proveedores_nuevos.csv")], "pedidos_csv": [str(tmp_path / "pedidos_nuevos.csv")]}


def test_las_altas_en_csv_entran_junto_al_excel(excel_pequeno, altas_csv, capsys):
    call_command("importar_maestro", excel=str(excel_pequeno))
    capsys.readouterr()

    call_command("importar_maestro", excel=str(excel_pequeno), **altas_csv)

    assert Proveedor.objects.count() == 3 and Pedido.objects.count() == 5
    muller = Proveedor.objects.get(codigo="P012")
    assert muller.nombre == "Müller & Partner GmbH" and muller.iban == "DE89370400440532013000" and muller.condiciones_dias == 30
    assert Pedido.objects.get(numero="PO-2026-0601").proveedor == muller
    assert Pedido.objects.get(numero="PO-2026-0602").proveedor.codigo == "P001"
    assert Pedido.objects.get(numero="PO-2026-0602").importe == Decimal("99.90")
    salida = capsys.readouterr().out
    assert "CSV: 1 proveedor, 3 pedidos" in salida
    assert "1 proveedor nuevo, 2 pedidos nuevos, 0 cambiados" in salida
    assert "Sin proveedor conocido, no se cargan: 2 (PO-2026-0999, PO-2026-0603)" in salida
    assert "Aviso: Proveedor P012 con NIF raro" in salida


def test_repetir_la_importacion_no_duplica_ni_pisa_lo_que_alberto_hizo_en_la_web(excel_pequeno, altas_csv, capsys):
    call_command("importar_maestro", excel=str(excel_pequeno), **altas_csv)
    Pedido.objects.filter(numero="PO-2026-0601").update(revisar=True, nota="Preguntar a Müller por el plazo")
    Pedido.objects.filter(numero="PO-2026-0007").update(revisar=False, nota="Ya lo miré")
    Proveedor.objects.filter(codigo="P012").update(activo=False)
    capsys.readouterr()

    call_command("importar_maestro", excel=str(excel_pequeno), **altas_csv)
    call_command("importar_maestro", excel=str(excel_pequeno), **altas_csv)

    assert Proveedor.objects.count() == 3 and Pedido.objects.count() == 5
    marcado = Pedido.objects.get(numero="PO-2026-0601")
    assert marcado.revisar and marcado.nota == "Preguntar a Müller por el plazo"
    desmarcado = Pedido.objects.get(numero="PO-2026-0007")
    assert not desmarcado.revisar and desmarcado.nota == "Ya lo miré"  # el Excel lo sigue marcando, pero la marca ya es de Alberto
    assert not Proveedor.objects.get(codigo="P012").activo
    assert capsys.readouterr().out.count("0 proveedores nuevos, 0 pedidos nuevos, 0 cambiados\n") == 2


def test_solo_los_csv_si_no_hay_excel_a_mano(altas_csv, tmp_path, monkeypatch, capsys):
    from upistas.config import settings as config
    from web.panel.management.commands import importar_maestro

    monkeypatch.setattr(importar_maestro, "settings", replace(config, caja_dir=tmp_path))
    Proveedor.objects.create(codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331", iban="ES2100491500051234567890")

    call_command("importar_maestro", **altas_csv)

    assert Proveedor.objects.count() == 2 and Pedido.objects.count() == 2
    assert "1 proveedor nuevo, 2 pedidos nuevos, 0 cambiados" in capsys.readouterr().out


def test_importar_maestro_avisa_si_no_encuentra_un_csv(excel_pequeno, tmp_path):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="No encuentro el CSV"):
        call_command("importar_maestro", excel=str(excel_pequeno), pedidos_csv=[str(tmp_path / "no_esta.csv")])


def test_importar_directamente_desde_el_adaptador_sin_pasar_por_el_comando(excel_pequeno, altas_csv):
    from pathlib import Path

    from upistas.adaptadores.fuentes.csv_altas import AltasCSV

    excel = MaestroExcel(excel_pequeno)
    altas = AltasCSV(tuple(Path(r) for r in altas_csv["proveedores_csv"]), tuple(Path(r) for r in altas_csv["pedidos_csv"]))
    resumen = MaestroDjango().importar(excel, altas)

    assert (resumen.proveedores_nuevos, resumen.pedidos_nuevos, resumen.cambiados) == (3, 5, 0)
    assert resumen.sin_proveedor == ("PO-2026-0999", "PO-2026-0603")
    assert str(resumen) == "3 proveedores nuevos, 5 pedidos nuevos, 0 cambiados"
    assert MaestroDjango().marcados_para_revisar() == frozenset({"PO-2026-0007"})


CSV_LOTE2 = settings.caja_dir / "proveedores_nuevos.csv", settings.caja_dir / "pedidos_nuevos.csv"


@pytest.mark.skipif(not (REAL.exists() and all(r.exists() for r in CSV_LOTE2)), reason="La Caja no está clonada")
def test_las_altas_de_verdad_del_lote_2_sobre_el_maestro_de_la_caja(capsys):
    call_command("importar_maestro", excel=str(REAL))
    capsys.readouterr()

    call_command("importar_maestro", excel=str(REAL), proveedores_csv=[str(CSV_LOTE2[0])], pedidos_csv=[str(CSV_LOTE2[1])])
    assert Proveedor.objects.count() == 15 and Pedido.objects.count() == 555
    assert Pedido.objects.filter(proveedor__codigo__in=["P012", "P013", "P014", "P015"]).count() == 5
    assert "4 proveedores nuevos, 39 pedidos nuevos, 0 cambiados" in capsys.readouterr().out

    call_command("importar_maestro", excel=str(REAL), proveedores_csv=[str(CSV_LOTE2[0])], pedidos_csv=[str(CSV_LOTE2[1])])
    assert Proveedor.objects.count() == 15 and Pedido.objects.count() == 555
    assert "0 proveedores nuevos, 0 pedidos nuevos, 0 cambiados" in capsys.readouterr().out
