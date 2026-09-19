"""«Importar datos»: subir ficheros de proveedores o de pedidos, ver fila a fila qué pasa y aplicar solo lo válido."""
from __future__ import annotations

import json
import os
import time
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from upistas.config import settings as ajustes
from web.panel import importaciones
from web.panel.models import Importacion, Pedido, Proveedor

pytestmark = pytest.mark.django_db

CAJA = ajustes.caja_dir
EXCEL = CAJA / "FINAL_v7_DEFINITIVO_ahorasi.xlsx"

CABECERA_PROVEEDORES = "ID,Razon Social,NIF,IBAN,Ciudad,Condiciones\n"
CABECERA_PEDIDOS = "pedido,proveedor_id,nif,importe_total,estado,fecha_pedido\n"


@pytest.fixture
def maestro():
    """Dos proveedores y dos pedidos, uno marcado y anotado por Alberto."""
    levante = Proveedor.objects.create(
        codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331",
        iban="ES2100491500051234567890", ciudad="Valencia", condiciones_dias=60,
    )
    Proveedor.objects.create(codigo="P003", nombre="Ofimática Cieza S.L.", nif="B30455812", iban="ES6001825322180201588391")
    Pedido.objects.create(numero="PO-2026-0001", proveedor=levante, importe=Decimal("2490.00"), fecha=date(2026, 1, 8))
    Pedido.objects.create(numero="PO-2026-0007", proveedor=levante, importe=Decimal("880.55"), revisar=True, nota="Llamar antes de pagar")
    return levante


@pytest.fixture
def almacen(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        yield tmp_path


def fichero(nombre: str, contenido: str | bytes) -> SimpleUploadedFile:
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
    return SimpleUploadedFile(nombre, datos, content_type="text/csv")


def subir(alberto, *ficheros) -> str:
    """Sube los ficheros y devuelve el token de la vista previa."""
    respuesta = alberto.post(reverse("panel:proveedor_importar"), {"ficheros": list(ficheros)})
    assert respuesta.status_code == 303
    return respuesta["Location"].rstrip("/").rsplit("/", 1)[-1]


def previa(alberto, token: str) -> str:
    return alberto.get(reverse("panel:proveedor_importar_previa", args=[token])).content.decode()


def aplicar(alberto, token: str):
    return alberto.post(reverse("panel:proveedor_importar_previa", args=[token]), {"accion": "aplicar"}, follow=True)


# --- la pantalla ---------------------------------------------------------------------------------------


def test_proveedores_lleva_a_importar_y_la_pantalla_explica_que_hacer(alberto, maestro):
    assert reverse("panel:proveedor_importar") in alberto.get(reverse("panel:proveedores")).content.decode()
    html = alberto.get(reverse("panel:proveedor_importar")).content.decode()
    assert "Importar datos" in html and "fichero de proveedores" in html and "fichero de pedidos" in html
    assert 'name="ficheros"' in html and "multiple" in html and 'id="zona-subida"' in html
    assert "No se guarda nada hasta que usted lo aplique" in html
    assert "Todavía no ha importado ningún fichero" in html


def test_sin_ficheros_o_con_uno_que_no_se_reconoce_lo_dice_llano(alberto, maestro, almacen):
    r = alberto.post(reverse("panel:proveedor_importar"), {}, follow=True)
    assert "No ha elegido ningún fichero." in r.content.decode()

    r = alberto.post(reverse("panel:proveedor_importar"), {"ficheros": [fichero("lista.csv", "nombre,telefono\nPepe,600000000\n")]}, follow=True)
    html = r.content.decode()
    assert "«lista.csv» no es un fichero de proveedores ni de pedidos" in html
    assert not list(almacen.glob("importaciones/*.json"))

    r = alberto.post(reverse("panel:proveedor_importar"), {"ficheros": [fichero("foto.pdf", b"%PDF\x81\x8d\x00raro")]}, follow=True)
    assert "«foto.pdf» no es un fichero de proveedores ni de pedidos" in r.content.decode()


def test_una_vista_previa_que_ya_no_esta_vuelve_al_principio(alberto, maestro, almacen):
    r = alberto.get(reverse("panel:proveedor_importar_previa", args=["no-existe-este-token"]), follow=True)
    assert r.redirect_chain[-1][0] == reverse("panel:proveedor_importar")
    assert "Esa vista previa ya no está" in r.content.decode()


# --- proveedores: nuevo, igual, cambia, inválido -------------------------------------------------------


def test_los_proveedores_se_clasifican_fila_a_fila(alberto, maestro, almacen):
    token = subir(alberto, fichero("proveedores.csv", CABECERA_PROVEEDORES
        + "P001,Suministros Levante S.L.,B46102331,ES21 0049 1500 0512 3456 7890,Valencia,60 dias\n"  # igual
        + "P003,Ofimática Cieza S.L.,B30455812,ES91 2100 0418 4502 0005 1332,Murcia,30 dias\n"  # cambia
        + "P012,Müller & Partner GmbH,DE812345678,DE89 3704 0044 0532 0130 00,Hamburg,30 dias\n"  # nuevo
        + "P013,Rara S.L.,1234,ES2100491500051234567890,,\n"  # NIF raro
        + "P014,Sin cuenta S.L.,B11111111,ES0001,,\n"  # IBAN que no vale
        + "P012,Müller otra vez,DE812345678,DE89 3704 0044 0532 0130 00,,\n"  # repetido
        + "P015,Con el NIF de otro,B46102331,ES9121000418450200051332,,\n"  # NIF de P001
        + "P016,Dos códigos,DE812345678,ES9121000418450200051332,,\n"))  # NIF de P012, que viene en el mismo fichero
    html = previa(alberto, token)

    assert "0 proveedores nuevos" not in html
    assert "<b>1 proveedor nuevo, 1 cambia, 5 filas inválidas</b>" in html
    assert "Fichero de proveedores · proveedores.csv" in html
    assert "1 nueva, 1 cambia, 1 ya estaba, 5 no valen" in html
    assert ">Ya está igual<" in html and "No hace nada" in html
    assert "Cuenta: <span class=\"mono\">ES6001825322180201588391</span> → <span class=\"mono\">ES9121000418450200051332</span>" in html
    assert "Ciudad: <span class=\"mono\">—</span> → <span class=\"mono\">Murcia</span>" in html
    assert "Días de pago: <span class=\"mono\">—</span> → <span class=\"mono\">30</span>" in html
    assert "El NIF «1234» no tiene un formato conocido." in html
    assert "La cuenta «ES0001» no es un IBAN." in html
    assert "Repetido: ya venía en la fila 4." in html
    assert "El NIF B46102331 ya es de Suministros Levante S.L. (P001)." in html
    assert "El NIF DE812345678 ya lo lleva P012 en este mismo envío." in html
    assert Proveedor.objects.count() == 2  # todavía no se ha guardado nada

    r = aplicar(alberto, token)
    assert r.redirect_chain[-1][0] == reverse("panel:proveedores")
    assert "Importado proveedores.csv: 1 nuevo, 1 cambiado, 5 filas sin importar." in r.content.decode()
    assert Proveedor.objects.count() == 3
    cieza = Proveedor.objects.get(codigo="P003")
    assert cieza.iban == "ES9121000418450200051332" and cieza.ciudad == "Murcia" and cieza.condiciones_dias == 30
    assert Proveedor.objects.get(codigo="P012").nombre == "Müller & Partner GmbH"
    hecho = Importacion.objects.get()
    assert (hecho.ficheros, hecho.nuevos, hecho.cambiados, hecho.invalidos) == ("proveedores.csv", 1, 1, 5)
    assert not list(almacen.glob("importaciones/*.json"))  # al aplicar, la vista previa se borra


def test_un_campo_mas_largo_que_su_columna_no_vale_y_dice_el_tope(alberto, maestro, almacen):
    """SQLite guardaría un código de 32 letras sin rechistar; la vista previa lo para antes."""
    codigo_largo = "P" + "0" * 31
    ciudad_larga = "Villa" * 20
    token = subir(alberto, fichero("largos.csv", CABECERA_PROVEEDORES
        + f"{codigo_largo},Largos S.L.,B11111111,ES9121000418450200051332,Murcia,30 dias\n"
        + f"P020,Lejos S.L.,B22222222,ES9121000418450200051332,{ciudad_larga},30 dias\n"
        + "P021,Bien S.L.,B33333333,ES9121000418450200051332,Murcia,30 dias\n"))
    html = previa(alberto, token)
    assert "<b>1 proveedor nuevo, 0 cambian, 2 filas inválidas</b>" in html
    assert f"El código «{codigo_largo}» es demasiado largo: como mucho 10 caracteres." in html
    assert f"La ciudad «{ciudad_larga}» es demasiado largo: como mucho 80 caracteres." in html

    aplicar(alberto, token)
    assert set(Proveedor.objects.values_list("codigo", flat=True)) == {"P001", "P003", "P021"}


def test_un_proveedor_que_cambia_solo_toca_los_campos_que_trae_el_fichero(alberto, maestro, almacen):
    token = subir(alberto, fichero("cuentas.csv", "ID;Razon Social;NIF;IBAN\nP001;Suministros Levante S.A.;B46102331;ES91 2100 0418 4502 0005 1332\n"))
    html = previa(alberto, token)
    assert "Nombre: <span class=\"mono\">Suministros Levante S.L.</span> → <span class=\"mono\">Suministros Levante S.A.</span>" in html
    assert "Ciudad" not in html.split("<tbody>")[1]

    aplicar(alberto, token)
    maestro.refresh_from_db()
    assert maestro.nombre == "Suministros Levante S.A." and maestro.iban == "ES9121000418450200051332"
    assert maestro.ciudad == "Valencia" and maestro.condiciones_dias == 60  # lo que el fichero no trae se queda


# --- pedidos ---------------------------------------------------------------------------------------------


def test_los_pedidos_se_clasifican_y_avisan_del_proveedor_desconocido(alberto, maestro, almacen):
    token = subir(alberto, fichero("pedidos.csv", CABECERA_PEDIDOS
        + "PO-2026-0001,P001,B46102331,2490.00,ABIERTO,2026-01-08\n"  # igual
        + "PO-2026-0007,P001,B46102331,\"900,00\",ABIERTO,20/01/2026\n"  # cambia (importe y fecha)
        + "PO-2026-0500,P003,B30455812,3139.66,ABIERTO,2026-08-17\n"  # nuevo
        + "PO-2026-0501,P404,,10.00,ABIERTO,2026-08-17\n"  # proveedor desconocido
        + "PO-2026-0502,P001,B46102331,mil,ABIERTO,2026-08-17\n"  # importe no numérico
        + "PO-2026-0503,P001,B46102331,10.00,ABIERTO,31/02/2026\n"  # fecha inválida
        + "PO-2026-0504,P001,B46102331,10.00,PERDIDO,2026-08-17\n"  # estado desconocido
        + "PO-2026-0500,P003,B30455812,1.00,ABIERTO,2026-08-17\n"  # repetido
        + "PO-2026-0505,P001,B30455812,10.00,ABIERTO,2026-08-17\n"  # NIF que no es el del proveedor
        + "pedido 12,P001,B46102331,10.00,ABIERTO,2026-08-17\n"))  # número raro
    html = previa(alberto, token)

    assert "<b>1 pedido nuevo, 1 cambia, 7 filas inválidas</b>" in html
    assert "Fichero de pedidos · pedidos.csv" in html
    assert "Importe: <span class=\"mono\">880,55 €</span> → <span class=\"mono\">900,00 €</span>" in html
    assert "Fecha: <span class=\"mono\">—</span> → <span class=\"mono\">20/01/2026</span>" in html
    assert "Ofimática Cieza S.L. · 3.139,66 € · 17/08/2026" in html
    assert "El proveedor P404 no está dado de alta ni viene en este envío." in html
    assert "El importe «mil» no es un número." in html
    assert "La fecha «31/02/2026» no se entiende." in html
    assert "El estado «PERDIDO» no se conoce." in html
    assert "Repetido: ya venía en la fila 4." in html
    assert "El NIF B30455812 no es el de Suministros Levante S.L. (P001)." in html
    assert "El número «PEDIDO 12» no tiene la forma PO-2026-0001." in html

    r = aplicar(alberto, token)
    assert "Importado pedidos.csv: 1 nuevo, 1 cambiado, 7 filas sin importar." in r.content.decode()
    assert Pedido.objects.count() == 3
    marcado = Pedido.objects.get(numero="PO-2026-0007")
    assert marcado.importe == Decimal("900.00") and marcado.fecha == date(2026, 1, 20)
    assert marcado.revisar is True and marcado.nota == "Llamar antes de pagar"  # lo de Alberto no se pisa
    assert Pedido.objects.get(numero="PO-2026-0500").proveedor.codigo == "P003"


def test_los_pedidos_pueden_apuntar_a_un_proveedor_que_llega_en_el_mismo_envio(alberto, maestro, almacen):
    proveedores = fichero("proveedores_nuevos.csv", CABECERA_PROVEEDORES + "P012,Müller & Partner GmbH,DE812345678,DE89 3704 0044 0532 0130 00,Hamburg,30 dias\n")
    pedidos = fichero("pedidos_nuevos.csv", CABECERA_PEDIDOS + "PO-2026-0601,P012,DE812345678,1234.50,ABIERTO,2026-08-17\n")
    token = subir(alberto, pedidos, proveedores)  # en el orden que sea: los proveedores se miran primero
    html = previa(alberto, token)
    assert "<b>1 proveedor nuevo, 1 pedido nuevo, 0 cambian, 0 filas inválidas</b>" in html
    assert html.index("proveedores_nuevos.csv") < html.index("pedidos_nuevos.csv")

    aplicar(alberto, token)
    assert Pedido.objects.get(numero="PO-2026-0601").proveedor.codigo == "P012"
    assert Importacion.objects.get().ficheros == "pedidos_nuevos.csv, proveedores_nuevos.csv"


def test_acepta_punto_y_coma_bom_y_cabeceras_del_excel(alberto, maestro, almacen):
    token = subir(alberto, fichero("pedidos_excel.csv", "﻿Pedido;ProveedorID;NIF;Importe_Total;Estado;Fecha_Pedido\nPO-2026-0700;P001;B46102331;2490,00;;2026-09-01\n".encode("utf-8")))
    html = previa(alberto, token)
    assert "<b>1 pedido nuevo, 0 cambian, 0 filas inválidas</b>" in html
    assert "Suministros Levante S.L. · 2.490,00 € · 01/09/2026" in html


def test_con_importe_e_importe_total_manda_la_misma_columna_para_decidir_y_para_ensenar(alberto, maestro, almacen):
    """`filas.py` prefiere «importe»; la vista previa enseña y explica esa misma celda, no la otra."""
    token = subir(alberto, fichero("dos_importes.csv", "pedido,proveedor_id,nif,importe,importe_total,estado,fecha_pedido\n"
        + "PO-2026-0700,P001,B46102331,10.00,99.00,ABIERTO,2026-09-01\n"
        + "PO-2026-0701,P001,B46102331,mil,20.00,ABIERTO,2026-09-01\n"))
    html = previa(alberto, token)
    assert "Suministros Levante S.L. · 10,00 € · 01/09/2026" in html and "99,00" not in html
    assert "El importe «mil» no es un número." in html and "«20.00»" not in html

    aplicar(alberto, token)
    assert Pedido.objects.get(numero="PO-2026-0700").importe == Decimal("10.00")


def test_un_fichero_con_caracteres_ilegibles_se_lee_pero_avisa_arriba(alberto, maestro, almacen):
    token = subir(alberto, fichero("roto.csv", b"ID,Razon Social,NIF,IBAN,Ciudad,Condiciones\nP020,Cer\x81micas S.L.,B50123456,ES2100491500051234567890,Zaragoza,60 dias\n"))
    html = previa(alberto, token)
    assert "«roto.csv» tiene caracteres que no se han podido leer: donde debía haber una letra sale «�»." in html
    assert "<b>1 proveedor nuevo, 0 cambian, 0 filas inválidas</b>" in html
    assert "Cer�micas S.L." in html


def test_un_fichero_que_no_se_reconoce_junto_a_uno_bueno_se_avisa_y_se_sigue(alberto, maestro, almacen):
    token = subir(alberto, fichero("lista.csv", "nombre,telefono\nPepe,600000000\n"),
                  fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0700,P001,B46102331,10.00,ABIERTO,2026-09-01\n"))
    html = previa(alberto, token)
    assert "«lista.csv» no es un fichero de proveedores ni de pedidos" in html
    assert "<b>1 pedido nuevo, 0 cambian, 0 filas inválidas</b>" in html


def test_cancelar_no_guarda_nada_y_borra_la_vista_previa(alberto, maestro, almacen):
    token = subir(alberto, fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0700,P001,B46102331,10.00,ABIERTO,2026-09-01\n"))
    assert (almacen / "importaciones" / f"{token}.json").is_file()

    r = alberto.post(reverse("panel:proveedor_importar_previa", args=[token]), {"accion": "cancelar"}, follow=True)

    assert r.redirect_chain[-1][0] == reverse("panel:proveedor_importar")
    assert "No se ha importado nada." in r.content.decode()
    assert Pedido.objects.count() == 2 and not Importacion.objects.exists()
    assert not (almacen / "importaciones" / f"{token}.json").exists()


def test_si_aplicar_falla_la_vista_previa_sigue_ahi(alberto, maestro, almacen, monkeypatch):
    token = subir(alberto, fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0700,P001,B46102331,10.00,ABIERTO,2026-09-01\n"))

    def falla(ficheros):
        raise RuntimeError("la base de datos no responde")

    monkeypatch.setattr(importaciones, "aplicar", falla)
    with pytest.raises(RuntimeError):
        alberto.post(reverse("panel:proveedor_importar_previa", args=[token]), {"accion": "aplicar"})

    assert (almacen / "importaciones" / f"{token}.json").is_file()
    assert Pedido.objects.count() == 2


def test_un_fichero_de_mas_de_10_mb_no_se_lee_y_se_dice_llano(alberto, maestro, almacen):
    gordo = fichero("enorme.csv", CABECERA_PEDIDOS.encode() + b"x" * (10 * 1024 * 1024))
    r = alberto.post(reverse("panel:proveedor_importar"), {"ficheros": [gordo]}, follow=True)
    assert "«enorme.csv» pesa más de 10 MB." in r.content.decode()
    assert not list(almacen.glob("importaciones/*.json"))

    token = subir(alberto, fichero("enorme.csv", CABECERA_PEDIDOS.encode() + b"x" * (10 * 1024 * 1024)),
                  fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0700,P001,B46102331,10.00,ABIERTO,2026-09-01\n"))
    html = previa(alberto, token)
    assert "«enorme.csv» pesa más de 10 MB." in html and "<b>1 pedido nuevo, 0 cambian, 0 filas inválidas</b>" in html


def test_sin_nada_que_aplicar_el_boton_no_se_puede_pulsar(alberto, maestro, almacen):
    token = subir(alberto, fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0001,P001,B46102331,2490.00,ABIERTO,2026-01-08\n"))
    html = previa(alberto, token)
    assert "No hay nada que aplicar." in html and 'value="aplicar" disabled' in html


# --- lo que espera entre pasos -----------------------------------------------------------------------------


def test_lo_parseado_espera_en_el_almacen_y_lo_viejo_se_borra(alberto, maestro, almacen):
    carpeta = almacen / "importaciones"
    carpeta.mkdir()
    viejo = carpeta / "viejo_viejo_viejo_1.json"
    viejo.write_text("[]", encoding="utf-8")
    hace_dos_dias = time.time() - 2 * 24 * 3600
    os.utime(viejo, (hace_dos_dias, hace_dos_dias))
    reciente = carpeta / "reciente_reciente_1.json"
    reciente.write_text("[]", encoding="utf-8")

    token = subir(alberto, fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0700,P001,B46102331,10.00,ABIERTO,2026-09-01\n"))

    assert not viejo.exists() and reciente.exists()
    guardado = json.loads((carpeta / f"{token}.json").read_text(encoding="utf-8"))
    assert guardado[0]["nombre"] == "pedidos.csv" and guardado[0]["tipo"] == "pedidos"
    assert guardado[0]["filas"] == [{"pedido": "PO-2026-0700", "proveedorid": "P001", "nif": "B46102331", "importetotal": "10.00", "estado": "ABIERTO", "fechapedido": "2026-09-01"}]
    assert "sessionid" not in alberto.cookies


def test_la_lista_de_ultimas_importaciones(alberto, maestro, almacen):
    token = subir(alberto, fichero("pedidos.csv", CABECERA_PEDIDOS + "PO-2026-0700,P001,B46102331,10.00,ABIERTO,2026-09-01\nmal,,,,,\n"))
    aplicar(alberto, token)
    html = alberto.get(reverse("panel:proveedor_importar")).content.decode()
    assert "Últimas importaciones" in html and "pedidos.csv" in html
    assert "Todavía no ha importado ningún fichero" not in html
    assert '<td class="num">1</td>' in html and '<td class="num">0</td>' in html


# --- los ficheros de verdad de La Caja -----------------------------------------------------------------------


@pytest.mark.skipif(not (EXCEL.exists() and (CAJA / "pedidos_nuevos.csv").exists()), reason="La Caja no está clonada")
def test_las_altas_de_verdad_del_lote_2_entran_enteras_y_solo_una_vez(alberto, almacen):
    call_command("importar_maestro", excel=str(EXCEL))
    assert Proveedor.objects.count() == 11
    ficheros = [SimpleUploadedFile(n, (CAJA / n).read_bytes()) for n in ("proveedores_nuevos.csv", "pedidos_nuevos.csv")]

    token = subir(alberto, *ficheros)
    html = previa(alberto, token)
    assert "<b>4 proveedores nuevos, 39 pedidos nuevos, 0 cambian, 0 filas inválidas</b>" in html
    assert "No vale" not in html

    r = aplicar(alberto, token)
    assert "Importado proveedores_nuevos.csv, pedidos_nuevos.csv: 43 nuevos, 0 cambiados." in r.content.decode()
    assert Proveedor.objects.count() == 15 and Pedido.objects.filter(proveedor__codigo="P014").exists()

    otra_vez = subir(alberto, *[SimpleUploadedFile(n, (CAJA / n).read_bytes()) for n in ("proveedores_nuevos.csv", "pedidos_nuevos.csv")])
    assert "<b>0 proveedores nuevos, 0 pedidos nuevos, 0 cambian, 0 filas inválidas</b>" in previa(alberto, otra_vez)
    aplicar(alberto, otra_vez)
    assert Proveedor.objects.count() == 15 and Pedido.objects.count() == 516 + 39
    assert [(i.nuevos, i.cambiados) for i in Importacion.objects.order_by("id")] == [(43, 0), (0, 0)]


# --- el módulo a pelo, sin pantalla ----------------------------------------------------------------------------


def test_leer_reconoce_el_tipo_por_las_cabeceras():
    assert importaciones.leer("a.csv", CABECERA_PROVEEDORES.encode() + b"P001,X,B46102331,ES2100491500051234567890,,\n").tipo == "proveedores"
    assert importaciones.leer("b.csv", b"Pedido;ProveedorID;Importe\nPO-2026-0001;P001;10\n").tipo == "pedidos"
    vacio = importaciones.leer("c.csv", b"")
    assert vacio.tipo is None and vacio.aviso == "«c.csv» está vacío."
    solo_cabecera = importaciones.leer("d.csv", CABECERA_PEDIDOS.encode())
    assert solo_cabecera.tipo is None and "solo trae la cabecera" in solo_cabecera.aviso
