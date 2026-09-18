from datetime import date
from decimal import Decimal

import pytest

from upistas.dominio.importes import normaliza_iban, parse_fecha, parse_importe


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("2.489,99", "2489.99"),
        ("12.874,40", "12874.40"),
        ("EUR 1498.30", "1498.30"),
        ("1,498.30", "1498.30"),
        ("522,90 €", "522.90"),
        ("184", "184"),
    ],
)
def test_parse_importe(texto, esperado):
    assert parse_importe(texto) == Decimal(esperado)


def test_parse_importe_vacio():
    assert parse_importe("") is None


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("08/01/2026", date(2026, 1, 8)),
        ("2026-01-08", date(2026, 1, 8)),
        ("15 de enero de 2026", date(2026, 1, 15)),
    ],
)
def test_parse_fecha(texto, esperado):
    assert parse_fecha(texto) == esperado


@pytest.mark.parametrize("texto", ["31/02/2026", "mañana", ""])
def test_parse_fecha_invalida(texto):
    assert parse_fecha(texto) is None


def test_normaliza_iban():
    assert normaliza_iban("es21 0049 1500") == "ES2100491500"
