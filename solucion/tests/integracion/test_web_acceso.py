"""La clave de acceso opcional (WEB_CLAVE): con ella la web pide una clave una vez; sin ella, todo sigue igual (#42)."""
import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

PUERTA = "Esta web es privada"
AVISO = "Esa clave no es. Pídasela a quien lleva el sistema."


@override_settings(WEB_CLAVE="")
def test_sin_clave_en_el_entorno_la_web_se_abre_sin_mas(alberto):
    r = alberto.get("/")
    assert r.status_code == 200 and PUERTA not in r.content.decode() and "acceso" not in r.cookies


@override_settings(WEB_CLAVE="abc")
def test_con_clave_la_portada_es_la_puerta_y_no_ensena_nada_de_la_web(alberto):
    r = alberto.get("/")
    html = r.content.decode()
    assert r.status_code == 200 and PUERTA in html and 'name="clave"' in html and 'type="password"' in html
    assert f"<title>{PUERTA} · Control de facturas</title>" in html and "Control de facturas · Pagos a proveedores" in html
    assert 'class="lado"' not in html and "csrfmiddlewaretoken" not in html and AVISO not in html
    assert 'name="siguiente" value="/"' in html


@override_settings(WEB_CLAVE="abc")
def test_salud_y_los_estaticos_no_piden_clave(alberto):
    salud = alberto.get("/salud/")
    assert salud.status_code == 200 and salud.content == b"ok"
    assert alberto.get("/static/panel/panel.css").status_code == 200


@override_settings(WEB_CLAVE="abc")
def test_una_clave_mala_vuelve_a_la_puerta_con_el_aviso_y_sin_cookie(alberto):
    r = alberto.post("/", {"clave": "otra", "siguiente": "/"})
    html = r.content.decode()
    assert r.status_code == 200 and AVISO in html and 'name="clave"' in html
    assert "acceso" not in r.cookies


@override_settings(WEB_CLAVE="abc")
def test_con_la_clave_buena_entra_donde_iba_y_no_la_vuelve_a_pedir(alberto):
    destino = reverse("panel:facturas") + "?resultado=PAGAR"
    r = alberto.post(reverse("panel:facturas"), {"clave": "abc", "siguiente": destino})
    assert r.status_code == 302 and r["Location"] == destino
    cookie = r.cookies["acceso"]
    assert cookie.value != "ok" and cookie["httponly"] and cookie["samesite"] == "Lax"  # firmada, no la palabra tal cual

    despues = alberto.get("/")
    html = despues.content.decode()
    assert despues.status_code == 200 and PUERTA not in html and 'class="lado"' in html


@override_settings(WEB_CLAVE="abc")
def test_una_cookie_inventada_no_abre_la_puerta(alberto):
    alberto.cookies["acceso"] = "ok"
    assert PUERTA in alberto.get("/").content.decode()


@override_settings(WEB_CLAVE="abc")
def test_una_peticion_de_htmx_sin_clave_hace_recargar_la_pagina(alberto):
    ruta = reverse("panel:facturas") + "?q=cervantes"
    r = alberto.get(ruta, headers={"HX-Request": "true"})
    assert r.status_code == 401 and r["HX-Redirect"] == ruta and r.content == b""


@override_settings(WEB_CLAVE="abc")
def test_un_siguiente_a_otro_dominio_no_se_sigue(alberto):
    r = alberto.post("/", {"clave": "abc", "siguiente": "https://otro.ejemplo.com/"})
    assert r.status_code == 302 and r["Location"] == "/"
