"""La web como producto terminado: páginas de error propias, sin rastro técnico, identidad y ajustes de producción (#32)."""
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

import web
from web.panel import consultas
from web.panel.templatetags.panel_extras import motivo_llano, norma
from web.panel.views import errores

pytestmark = pytest.mark.django_db

SETTINGS_PY = str(Path(web.__file__).parent / "settings.py")
RAIZ = Path(web.__file__).parent.parent


def _ajustes(monkeypatch, **entorno) -> dict:
    """Carga settings.py de cero con solo estas variables (las del .env del que ejecuta no cuentan)."""
    for v in ("DJANGO_DEBUG", "DJANGO_SECRET_KEY", "DJANGO_HTTPS", "DJANGO_ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS"):
        monkeypatch.delenv(v, raising=False)
    for k, v in entorno.items():
        monkeypatch.setenv(k, v)
    return runpy.run_path(SETTINGS_PY)


# --- 1) DEBUG apagado y páginas de error propias ---


@override_settings(DEBUG=False)
def test_la_404_es_nuestra_y_lleva_a_hoy(alberto):
    r = alberto.get("/esta-pagina-no-esta/")
    html = r.content.decode()
    assert r.status_code == 404
    assert "Esta página no existe" in html and 'href="' + reverse("panel:inicio") + '"' in html
    assert "<title>Esta página no existe · Pagos de Alberto</title>" in html
    assert 'class="lado"' in html  # con la barra lateral: Alberto sigue en la web
    assert "Not Found" not in html and "Traceback" not in html


@override_settings(DEBUG=False)
def test_la_500_es_nuestra_y_no_toca_la_base_de_datos():
    r = errores.algo_fallo(RequestFactory().get("/"))
    html = r.content.decode()
    assert r.status_code == 500
    assert "Algo ha fallado" in html and "No se ha perdido nada" in html and reverse("panel:inicio") in html
    assert "Server Error" not in html and "panel.css" in html


@override_settings(DEBUG=False)
def test_un_formulario_sin_su_marca_de_seguridad_ensena_nuestra_403():
    r = Client(enforce_csrf_checks=True).post(reverse("panel:sincronizar"), {})
    html = r.content.decode()
    assert r.status_code == 403
    assert "llevaba demasiado tiempo abierta" in html and "CSRF verification failed" not in html and "Forbidden" not in html


@override_settings(DEBUG=False)
def test_sin_debug_los_estaticos_y_las_letras_se_sirven_igual(alberto):
    css = alberto.get("/static/panel/panel.css")
    assert css.status_code == 200 and "text/css" in css["Content-Type"]
    letra = alberto.get("/static/panel/fuentes/inter-latin.woff2")
    assert letra.status_code == 200 and b"".join(letra.streaming_content)[:4] == b"wOF2"
    manifiesto = alberto.get("/static/panel/manifest.webmanifest")
    assert manifiesto.status_code == 200 and manifiesto["Content-Type"].startswith("application/manifest+json")


def test_collectstatic_reune_los_ficheros_vendidos(tmp_path):
    with override_settings(STATIC_ROOT=tmp_path):
        call_command("collectstatic", interactive=False, verbosity=0)
    assert (tmp_path / "panel" / "panel.css").exists() and (tmp_path / "panel" / "fuentes" / "inter-latin.woff2").exists()
    assert (tmp_path / "panel" / "htmx.min.js").exists() and (tmp_path / "panel" / "marca.svg").exists()
    assert (tmp_path / "panel" / "panel.css.gz").exists()  # WhiteNoise deja la copia comprimida


# --- 2) Sin rastro técnico a la vista ---


def test_todas_las_pantallas_llevan_el_pie_y_nada_mas(alberto, lote_de_prueba):
    for nombre in ("inicio", "facturas", "proveedores", "cola", "ejecuciones", "conexion", "asientos", "subir"):
        html = alberto.get(reverse("panel:" + nombre)).content.decode()
        assert '<footer class="pie">Pagos de Alberto · Banco Miralmar</footer>' in html, nombre
        for rastro in ("GitHub", "github", "localhost", "en construcción", "en desarrollo"):
            assert rastro not in html, (nombre, rastro)


def test_las_reglas_nuevas_tienen_nombre_en_palabras_y_nunca_sale_el_id():
    for id_regla in ("R0_lectura", "R3_datos_fiscales", "R5_hash_previo", "R5_copia_hash", "R5_reenvio",
                     "R6_contenido_oculto", "R6_evaluacion_disponible", "R6_maestro_verificable"):
        assert consultas.nombre_regla(id_regla) != id_regla and "_" not in consultas.nombre_regla(id_regla)
    assert consultas.nombre_regla("R11_algo_nuevo") == "Comprobación 11"
    assert consultas.nombre_regla("rara") == "Otra comprobación"


def test_la_norma_se_dice_en_palabras(alberto, lote_de_prueba):
    assert norma("v3") == "versión 3 de la norma" and norma("v4") == "versión 4 de la norma" and norma(None) == "norma en vigor"
    assert motivo_llano("Cumple la norma v3") == "Cumple la norma" and motivo_llano(None) == ""
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "versión 3 de la norma" in html and "norma v3" not in html
    detalle = alberto.get(reverse("panel:factura", args=["lote1", "2026-01-08_P001.pdf"])).content.decode()
    assert "Las comprobaciones de la versión 3 de la norma" in detalle and "norma v3" not in detalle


def test_la_huella_de_la_copia_del_erp_no_sale_arriba(alberto, lote_de_prueba):
    from django.utils import timezone

    from web.panel.models import SincronizacionERP, VersionERP

    ahora = timezone.now()
    huella = "a1b2c3d4e5f60718"
    VersionERP.objects.create(version=huella, creada=ahora, n_asientos=516)
    SincronizacionERP.objects.create(inicio=ahora, fin=ahora, ok=True, n_asientos=516, version_id=huella)
    html = alberto.get(reverse("panel:conexion")).content.decode()
    assert "ver sus asientos" in html and f'<span class="mono">{huella}</span>' not in html


# --- 3) Identidad ---


def test_identidad_en_la_cabecera(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert '<html lang="es">' in html and "<title>Hoy · Pagos de Alberto</title>" in html
    assert '<meta name="description" content="Las facturas de Alberto en Banco Miralmar' in html
    assert 'rel="icon" type="image/svg+xml" href="/static/panel/marca.svg' in html
    assert 'rel="manifest" href="/static/panel/manifest.webmanifest' in html
    assert '<meta name="application-name" content="Pagos de Alberto">' in html
    manifiesto = json.loads((RAIZ / "web" / "panel" / "static" / "panel" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifiesto["name"] == "Pagos de Alberto" and manifiesto["lang"] == "es" and manifiesto["icons"][0]["src"] == "marca.svg"


def test_cada_pantalla_tiene_su_titulo(alberto, lote_de_prueba):
    for nombre, titulo in (("facturas", "Facturas"), ("proveedores", "Proveedores"), ("cola", "Para revisar"), ("subir", "Subir facturas")):
        assert f"<title>{titulo} · Pagos de Alberto</title>" in alberto.get(reverse("panel:" + nombre)).content.decode()


# --- 4) Ajustes de producción ---


def test_sin_variables_la_web_arranca_como_en_produccion(monkeypatch):
    """Sin ninguna variable la web arranca sin DEBUG y con una clave generada en el portátil (no vale para un servidor)."""
    ajustes = _ajustes(monkeypatch)
    assert ajustes["DEBUG"] is False and ajustes["SECRET_KEY_GENERADA"] is True and len(ajustes["SECRET_KEY"]) >= 50
    assert ajustes["SECURE_CONTENT_TYPE_NOSNIFF"] is True and ajustes["X_FRAME_OPTIONS"] == "SAMEORIGIN"
    assert ajustes["SECURE_REFERRER_POLICY"] == "same-origin" and "SECURE_SSL_REDIRECT" not in ajustes


def test_con_clave_en_el_entorno_se_usa_esa_y_no_se_genera_ninguna(monkeypatch):
    ajustes = _ajustes(monkeypatch, DJANGO_SECRET_KEY="una-clave-larga-de-verdad")
    assert ajustes["SECRET_KEY"] == "una-clave-larga-de-verdad" and ajustes["SECRET_KEY_GENERADA"] is False


def test_la_clave_generada_se_conserva_entre_arranques(monkeypatch):
    primera = _ajustes(monkeypatch)["SECRET_KEY"]
    assert _ajustes(monkeypatch)["SECRET_KEY"] == primera


def test_con_debug_vale_la_clave_de_desarrollo(monkeypatch):
    ajustes = _ajustes(monkeypatch, DJANGO_DEBUG="1")
    assert ajustes["DEBUG"] is True and len(ajustes["SECRET_KEY"]) >= 50


def test_con_https_las_cookies_van_seguras_y_se_confia_en_el_proxy(monkeypatch):
    ajustes = _ajustes(monkeypatch, DJANGO_SECRET_KEY="x", DJANGO_HTTPS="1",
                       DJANGO_ALLOWED_HOSTS="pagos.ejemplo.com", CSRF_TRUSTED_ORIGINS="https://pagos.ejemplo.com, ")
    assert ajustes["SESSION_COOKIE_SECURE"] and ajustes["CSRF_COOKIE_SECURE"] and ajustes["SECURE_SSL_REDIRECT"]
    assert ajustes["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https") and ajustes["SECURE_HSTS_SECONDS"] > 0
    assert ajustes["ALLOWED_HOSTS"] == ["pagos.ejemplo.com"] and ajustes["CSRF_TRUSTED_ORIGINS"] == ["https://pagos.ejemplo.com"]


def test_check_deploy_no_avisa_con_las_variables_puestas():
    entorno = {**os.environ, "PYTHONUTF8": "1", "DJANGO_DEBUG": "0", "DJANGO_HTTPS": "1",
               "DJANGO_SECRET_KEY": "k" * 30 + "una-clave-de-mas-de-cincuenta-caracteres-distintos",
               "DJANGO_ALLOWED_HOSTS": "pagos.ejemplo.com", "CSRF_TRUSTED_ORIGINS": "https://pagos.ejemplo.com"}
    entorno.pop("DJANGO_SETTINGS_MODULE", None)
    r = subprocess.run([sys.executable, "manage.py", "check", "--deploy"], cwd=RAIZ, env=entorno, capture_output=True, text=True)
    assert r.returncode == 0 and "no issues" in r.stdout, r.stdout + r.stderr


def test_salud_responde_en_texto_llano(alberto):
    r = alberto.get("/salud/")
    assert r.status_code == 200 and r.content == b"ok" and r["Content-Type"].startswith("text/plain")
    assert alberto.post("/salud/").status_code == 405


def test_las_variables_estan_documentadas():
    ejemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    doc = (RAIZ / "docs" / "web.md").read_text(encoding="utf-8")
    for variable in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_HTTPS", "DJANGO_ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS"):
        assert variable in ejemplo and variable in doc, variable
    assert "## En producción" in doc and "/salud/" in doc
