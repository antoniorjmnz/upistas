"""`manage.py comprobar_despliegue`: dice en llano qué le falta al entorno para servir la web fuera del portátil."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings

pytestmark = pytest.mark.django_db

CLAVE = "x" * 50


@pytest.fixture
def entorno_de_produccion(monkeypatch, tmp_path):
    """Todo lo que pide el despliegue: variables, Postgres (fingido), almacén escribible y estáticos recogidos."""
    monkeypatch.setenv("HELMCODE_API_KEY", "clave-helmcode")
    monkeypatch.delenv("ASISTENTE_API_KEY", raising=False)
    monkeypatch.setenv("ERP_URL", "https://erp.ejemplo.com")
    monkeypatch.setenv("HOY", "2026-09-18")
    monkeypatch.setattr(connection, "vendor", "postgresql")
    estaticos = tmp_path / "staticfiles"
    (estaticos / "panel").mkdir(parents=True)
    (estaticos / "panel" / "panel.css").write_text("/* recogido */", encoding="utf-8")
    with override_settings(
        DEBUG=False, SECRET_KEY=CLAVE, ALLOWED_HOSTS=["facturas.ejemplo.com"],
        CSRF_TRUSTED_ORIGINS=["https://facturas.ejemplo.com"], MEDIA_ROOT=tmp_path / "almacen", STATIC_ROOT=estaticos,
    ):
        yield tmp_path


def comprobar() -> str:
    salida = StringIO()
    call_command("comprobar_despliegue", stdout=salida)
    return salida.getvalue()


def test_con_todo_puesto_dice_que_esta_listo(entorno_de_produccion):
    salida = comprobar()

    assert "Falta" not in salida
    assert "Aviso" not in salida
    assert "Todo listo para desplegar." in salida
    assert "Bien   HOY fija la fecha de referencia en 2026-09-18" in salida
    assert "Bien   Las tablas están al día" in salida
    assert (entorno_de_produccion / "almacen").is_dir()


def test_en_el_portatil_dice_cada_cosa_que_falta(monkeypatch, tmp_path):
    monkeypatch.delenv("HELMCODE_API_KEY", raising=False)
    monkeypatch.delenv("ASISTENTE_API_KEY", raising=False)
    monkeypatch.setenv("ERP_URL", "http://127.0.0.1:8009")
    monkeypatch.delenv("HOY", raising=False)
    salida = StringIO()

    with override_settings(DEBUG=True, SECRET_KEY="solo-desarrollo-no-usar-en-produccion", ALLOWED_HOSTS=["127.0.0.1", "localhost"],
                           CSRF_TRUSTED_ORIGINS=[], MEDIA_ROOT=tmp_path / "almacen", STATIC_ROOT=tmp_path / "staticfiles"):
        with pytest.raises(CommandError, match="Faltan 9 cosas para desplegar."):
            call_command("comprobar_despliegue", stdout=salida)

    texto = salida.getvalue()
    for falta in ("DJANGO_DEBUG=0", "DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "HELMCODE_API_KEY",
                  "ASISTENTE_API_KEY", "ERP_URL", "DATABASE_URL=postgresql://", "collectstatic"):
        assert f"Falta  " in texto and falta in texto, falta
    assert "Aviso  HOY no está" in texto
    assert "Bien   Conecto con la base de datos" in texto
    assert "Bien   El almacén se puede escribir" in texto


def test_una_sola_cosa_que_falta_va_en_singular(entorno_de_produccion, monkeypatch):
    monkeypatch.delenv("HELMCODE_API_KEY")
    monkeypatch.setenv("ASISTENTE_API_KEY", "clave-del-asistente")  # «Preguntar» sigue teniendo la suya

    with pytest.raises(CommandError, match="Falta 1 cosa para desplegar."):
        comprobar()


def test_avisa_si_el_almacen_no_se_puede_escribir(entorno_de_produccion, tmp_path):
    fichero = tmp_path / "no-soy-carpeta"
    fichero.write_text("", encoding="utf-8")
    salida = StringIO()

    with override_settings(MEDIA_ROOT=fichero):
        with pytest.raises(CommandError, match="Falta 1 cosa"):
            call_command("comprobar_despliegue", stdout=salida)

    assert "Falta  No puedo escribir en el almacén" in salida.getvalue()
