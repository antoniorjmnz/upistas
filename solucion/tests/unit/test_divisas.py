from decimal import Decimal
from pathlib import Path

import pytest

from upistas.dominio.divisas import TiposDeCambio, al_cambio, cuadra_al_cambio, importe_es, tipo_es
from upistas.dominio.norma import Norma

NORMAS = Path(__file__).resolve().parents[2] / "normas"
TIPOS = {"USD": Decimal("1.0870"), "JPY": Decimal("162.07")}


def test_al_cambio_divide_por_el_tipo_y_redondea_a_centimos():
    assert al_cambio(Decimal("2450"), "USD", TIPOS) == Decimal("2253.91")
    assert al_cambio(Decimal("850000"), "JPY", TIPOS) == Decimal("5244.65")


def test_al_cambio_sin_tipo_o_sin_importe_no_inventa():
    assert al_cambio(Decimal("2450"), "CAD", TIPOS) is None
    assert al_cambio(None, "USD", TIPOS) is None
    assert al_cambio(Decimal("1"), "USD", {}) is None


@pytest.mark.parametrize("en_euros,cuadra", [("2253.91", True), ("2242.73", True), ("2242.72", False), ("2100", False)])
def test_cuadra_al_cambio_con_medio_por_ciento_del_pedido(en_euros, cuadra):
    assert cuadra_al_cambio(Decimal(en_euros), Decimal("2254"), Decimal("0.5")) is cuadra


def test_importes_y_tipos_se_escriben_en_espanol():
    assert importe_es(Decimal("2450"), "USD") == "2.450,00 USD"
    assert importe_es(Decimal("2254")) == "2.254,00 €"
    assert importe_es(Decimal("1234567.5"), "JPY") == "1.234.567,50 JPY"
    assert tipo_es(Decimal("1.087")) == "1,0870"
    assert tipo_es(Decimal("162.07")) == "162,0700"


def test_la_tabla_de_tipos_del_repo_se_carga_con_la_norma():
    norma = Norma.desde_toml(NORMAS / "v3.toml")
    assert set(norma.divisas.tipos) == {"USD", "GBP", "CHF", "JPY", "BRL", "MXN"}
    assert norma.divisas.tipos["USD"] == Decimal("1.087") and norma.divisas.tipos["MXN"] == Decimal("21.31")
    assert norma.divisas.tolerancia_pct == Decimal("0.5")


def test_una_norma_sin_tabla_de_divisas_no_tiene_tipos(tmp_path):
    ruta = tmp_path / "n.toml"
    ruta.write_text('version = "t"\n[reglas.R2_divisa]\nsi_falla = "ESCALAR"\n', encoding="utf-8")
    assert Norma.desde_toml(ruta).divisas == TiposDeCambio()


def test_desde_datos_normaliza_codigos_y_decimales():
    tipos = TiposDeCambio.desde_datos({"tipos": {"usd": 1.087}, "tolerancia_pct": 1})
    assert tipos.tipos == {"USD": Decimal("1.087")} and tipos.tolerancia_pct == Decimal("1")
    assert TiposDeCambio.desde_datos({}) == TiposDeCambio()
