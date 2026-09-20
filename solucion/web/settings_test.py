"""Ajustes para los tests: base de datos temporal y fecha fija.

pytest-django configura Django antes de cargar cualquier conftest, así que esto tiene que
ocurrir aquí, antes de que nadie importe `upistas.config`.
"""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="upistas-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.sqlite').as_posix()}"
os.environ["HOY"] = "2026-09-18"
# La web arranca sin DEBUG y exige su clave; en los tests vale una fija, si el .env no trae otra.
os.environ.setdefault("DJANGO_SECRET_KEY", "clave-solo-para-los-tests")

from web.settings import *  # noqa: E402, F401, F403

# Los workers de DBOS escriben desde varios hilos: la base de datos de tests tiene que ser un
# fichero (WAL), no la de memoria compartida que usa Django por defecto, que se bloquea por tabla.
DATABASES["default"]["TEST"] = {"NAME": str(_tmp / "test_django.sqlite")}  # noqa: F405

# Los tests nunca pasan por la puerta de la clave, tenga lo que tenga el .env de quien los ejecuta.
WEB_CLAVE = ""
