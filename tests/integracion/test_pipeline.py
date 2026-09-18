from pathlib import Path

import pytest
from dbos import DBOS

from upistas.infra import pipeline


@pytest.fixture(scope="module")
def dbos_lanzado():
    pipeline.iniciar()
    yield
    DBOS.destroy()


def test_documento_ilegible_acaba_en_escalar(dbos_lanzado):
    h = pipeline.encolar_lote([Path("no_existe/factura_1.txt")], lote="test", version_norma="v3")[0]
    out = h.get_result()
    assert out["file_id"] == "factura_1.txt"
    assert out["result"] == "ESCALAR"


def test_reprocesar_el_mismo_lote_no_duplica(dbos_lanzado):
    a = pipeline.encolar_lote([Path("x/factura_2.txt")], lote="test", version_norma="v3")[0]
    b = pipeline.encolar_lote([Path("x/factura_2.txt")], lote="test", version_norma="v3")[0]
    assert a.get_workflow_id() == b.get_workflow_id()
    assert a.get_result() == b.get_result()
