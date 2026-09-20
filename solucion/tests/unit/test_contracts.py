import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from upistas.contracts.decision import Decision
from upistas.contracts.factura_extraida import FacturaExtraida

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_ejemplo_factura_extraida_valida():
    f = FacturaExtraida.model_validate(load("factura_extraida.ok.json"))
    assert f.campos.total.valor == 3012.89
    assert f.documento.sha256 and f.documento.tipo.value == "texto"


def test_ejemplo_con_nota_valida():
    f = FacturaExtraida.model_validate(load("factura_extraida.nota.ok.json"))
    assert f.notas[0].categorias[0].value == "pide_saltar_regla"


def test_factura_extraida_invalida_falla():
    with pytest.raises(ValidationError):
        FacturaExtraida.model_validate(load("factura_extraida.bad.json"))


def test_ejemplo_decision_valida():
    d = Decision.model_validate(load("decision.ok.json"))
    assert d.result.value == "PAGAR" and d.version_datos


def test_decision_con_result_invalido_falla():
    with pytest.raises(ValidationError):
        Decision.model_validate(load("decision.bad.json"))
