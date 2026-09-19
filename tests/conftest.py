from functools import cache

import pytest

# DBOS lee DATABASE_URL al importar el pipeline: cada sesión de tests usa su propia SQLite.


@pytest.fixture(autouse=True)
def no_usar_excel_real_en_tests(monkeypatch, request):
    from upistas.infra import contenedor
    from upistas.adaptadores.fuentes.memoria import ErpEnMemoria

    erp_original = contenedor.erp

    @cache
    def erp_local():
        if contenedor.settings.erp_snapshot is not None:
            erp_original.cache_clear()
            return erp_original()
        return ErpEnMemoria()

    if request.node.get_closest_marker("django_db") is None:
        monkeypatch.setattr(contenedor, "erp", erp_local)
    monkeypatch.setattr(contenedor, "rutas_maestro", lambda: ())
    contenedor.maestro.cache_clear()
    contenedor.referencias.cache_clear()
    yield
    contenedor.maestro.cache_clear()
    contenedor.referencias.cache_clear()
