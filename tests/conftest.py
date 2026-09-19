import os
import tempfile
from pathlib import Path

import pytest

# DBOS lee DATABASE_URL al importar el pipeline: cada sesión de tests usa su propia SQLite.
_tmp = Path(tempfile.mkdtemp(prefix="upistas-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.sqlite').as_posix()}"


@pytest.fixture(autouse=True)
def no_usar_excel_real_en_tests(monkeypatch):
    from upistas.infra import contenedor

    monkeypatch.setattr(contenedor, "rutas_maestro", lambda: ())
    contenedor.maestro.cache_clear()
    contenedor.referencias.cache_clear()
    yield
    contenedor.maestro.cache_clear()
    contenedor.referencias.cache_clear()
