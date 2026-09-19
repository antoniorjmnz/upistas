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

from web.settings import *  # noqa: E402, F401, F403
