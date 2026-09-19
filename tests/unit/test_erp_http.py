from datetime import date
from decimal import Decimal

import httpx
import pytest

from upistas.adaptadores.fuentes.erp_http import ErpHTTP


def xml(contenido, status=200, headers=None):
    cuerpo = '<?xml version="1.0" encoding="ISO-8859-1"?>' + contenido
    return httpx.Response(status, content=cuerpo.encode("iso-8859-1"), headers=headers)


def pagina(numero=1, paginas=1, total=1, pedido="PO-2026-0001", identificador="AS-00999", importe="1.210,40"):
    return xml(f"""<respuesta><meta><pagina>{numero}</pagina><paginas>{paginas}</paginas><total>{total}</total></meta>
    <asientos><asiento><id>{identificador}</id><fecha>15/01/2026</fecha><proveedor>P001</proveedor>
    <nif>B12345678</nif><pedido>{pedido}</pedido><importe>{importe}</importe><estado>PENDIENTE</estado>
    </asiento></asientos></respuesta>""")


def fuente(handler, pausas=None):
    return ErpHTTP("http://erp.test", "demo", "clave-test", transport=httpx.MockTransport(handler), intervalo=0, dormir=(pausas if pausas is not None else []).append)


def test_descarga_todas_las_paginas_y_no_confunde_asiento_con_pedido():
    consultas = []

    def handler(request):
        if request.url.path == "/erp/login":
            assert request.method == "POST"
            assert request.content == b"usuario=demo&clave=clave-test"
            return xml("<sesion><token>token-test</token></sesion>")
        assert request.headers["X-ERP-Token"] == "token-test"
        numero = int(request.url.params["pagina"])
        consultas.append(numero)
        return pagina(numero, 2, 2, f"PO-2026-{numero:04}", f"AS-{numero + 100:05}")

    asientos = fuente(handler).asientos()
    assert consultas == [1, 2]
    assert len(asientos) == 2
    assert asientos[0].id == "AS-00101"
    assert asientos[0].pedido == "PO-2026-0001"
    assert asientos[0].importe == Decimal("1210.40")
    assert asientos[0].fecha == date(2026, 1, 15)


def test_reintenta_ora_y_rate_limit_y_renueva_sesion_en_la_misma_pagina():
    logins = []
    consultas = []
    pausas = []

    def handler(request):
        if request.url.path == "/erp/login":
            logins.append(1)
            return xml(f"<sesion><token>token-{len(logins)}</token></sesion>")
        consultas.append(request.url.params["pagina"])
        intento = len(consultas)
        if intento == 1:
            return xml("<error><codigo>ORA-00600</codigo></error>", 500)
        if intento == 2:
            return xml("<error><codigo>ERP-429</codigo></error>", 429, {"Retry-After": "0.2"})
        if intento == 3:
            return xml("<error><codigo>SES-401</codigo></error>", 401)
        assert request.headers["X-ERP-Token"] == "token-2"
        return pagina()

    assert len(fuente(handler, pausas).asientos()) == 1
    assert consultas == ["1", "1", "1", "1"]
    assert len(logins) == 2
    assert 0.2 in pausas


def test_fallo_de_red_tiene_reintentos_limitados():
    intentos = []

    def handler(request):
        intentos.append(1)
        raise httpx.ConnectError("sin conexión", request=request)

    with pytest.raises(ValueError, match="ERP"):
        fuente(handler).asientos()
    assert len(intentos) == 5


def test_credenciales_incorrectas_no_se_reintentan_ni_se_imprimen():
    intentos = []

    def handler(request):
        intentos.append(1)
        return xml("<error><codigo>SES-401</codigo></error>", 401)

    with pytest.raises(ValueError, match="SES-401") as error:
        fuente(handler).asientos()
    assert len(intentos) == 1
    assert "clave-test" not in str(error.value)


@pytest.mark.parametrize("caso", ["total_incompleto", "pedido_repetido", "pagina_incorrecta", "importe_invalido", "xml_invalido", "sesion_sin_token"])
def test_no_devuelve_una_replica_incompleta_o_invalida(caso):
    def handler(request):
        if request.url.path == "/erp/login":
            return xml("<sesion/>" if caso == "sesion_sin_token" else "<sesion><token>token-test</token></sesion>")
        if caso == "xml_invalido":
            return xml("<respuesta>")
        if caso == "importe_invalido":
            return pagina(importe="ilegible")
        if caso == "total_incompleto":
            return pagina(total=2)
        if caso == "pagina_incorrecta":
            return pagina(numero=2)
        numero = int(request.url.params["pagina"])
        return pagina(numero, 2, 2, identificador=f"AS-{numero:05}")

    with pytest.raises(ValueError):
        fuente(handler).asientos()
