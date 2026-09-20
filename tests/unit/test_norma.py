from datetime import date

import pytest

from upistas.dominio.modelos import Factura, Referencias, Resultado
from upistas.dominio.norma import Norma

HOY = date(2026, 9, 18)
REFS = Referencias(proveedores={}, pedidos={}, asientos={}, hoy=HOY)


def norma(tmp_path, contenido: str) -> Norma:
    ruta = tmp_path / "n.toml"
    ruta.write_text(contenido, encoding="utf-8")
    return Norma.desde_toml(ruta)


def test_factura_que_cumple_se_paga(tmp_path):
    n = norma(tmp_path, 'version = "t"\n[reglas.R4_fecha]\nsi_falla = "ESCALAR"\n')
    d = n.evaluar(Factura("a.pdf", fecha=date(2026, 1, 8)), REFS)
    assert d.resultado is Resultado.PAGAR


def test_fecha_futura_escala_con_motivo(tmp_path):
    n = norma(tmp_path, 'version = "t"\n[reglas.R4_fecha]\nsi_falla = "ESCALAR"\n')
    d = n.evaluar(Factura("a.pdf", fecha=date(2027, 1, 1)), REFS)
    assert d.resultado is Resultado.ESCALAR
    assert "futura" in d.motivo


def test_la_norma_decide_la_consecuencia(tmp_path):
    n = norma(tmp_path, 'version = "t"\n[reglas.R4_fecha]\nsi_falla = "NO_PAGAR"\n')
    sin_fecha = Factura("a.pdf", ausentes=frozenset({"fecha"}))  # el lector está seguro de que no la trae
    assert n.evaluar(sin_fecha, REFS).resultado is Resultado.NO_PAGAR


def test_norma_con_regla_inexistente_falla_al_cargar(tmp_path):
    with pytest.raises(KeyError, match="R99"):
        norma(tmp_path, 'version = "t"\n[reglas.R99_inventada]\nsi_falla = "ESCALAR"\n')


def test_la_norma_v3_del_repo_carga():
    from upistas.config import ROOT

    assert Norma.desde_toml(ROOT / "normas" / "v3.toml").version == "v3"
