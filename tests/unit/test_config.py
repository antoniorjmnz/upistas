from pathlib import Path

import pytest

from upistas.config import base_de_datos_django, ruta_sqlite, url_dbos


def test_sqlite_windows_y_posix():
    assert ruta_sqlite("sqlite:///C:/Users/antor/upistas.sqlite") == Path("C:/Users/antor/upistas.sqlite")
    assert ruta_sqlite("sqlite:////home/fran/upistas.sqlite") == Path("/home/fran/upistas.sqlite")


def test_en_sqlite_dbos_usa_un_fichero_hermano():
    assert url_dbos("sqlite:///C:/x/upistas.sqlite") == "sqlite:///C:/x/upistas.dbos.sqlite"
    assert base_de_datos_django("sqlite:///C:/x/upistas.sqlite")["NAME"] == str(Path("C:/x/upistas.sqlite"))


def test_en_postgres_comparten_la_misma_base():
    url = "postgresql://upistas:s%40cret@db.local:5433/alberto"
    assert url_dbos(url) == url
    d = base_de_datos_django(url)
    assert (d["ENGINE"], d["NAME"], d["USER"], d["PASSWORD"], d["HOST"], d["PORT"]) == (
        "django.db.backends.postgresql", "alberto", "upistas", "s@cret", "db.local", 5433)


def test_otros_motores_se_rechazan_con_mensaje_claro():
    with pytest.raises(ValueError, match="no soportada"):
        base_de_datos_django("mysql://x")
