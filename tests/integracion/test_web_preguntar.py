"""Preguntar: la pantalla del asistente mientras Fran lo termina (#39). Honesta y sin nada que mandar."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def preguntar(alberto) -> str:
    respuesta = alberto.get(reverse("panel:preguntar"))
    assert respuesta.status_code == 200
    return respuesta.content.decode()


def test_explica_para_que_sirve_y_que_podra_preguntar(alberto):
    html = preguntar(alberto)
    assert "Pregunte lo que quiera" in html
    assert "le llevará a la pantalla donde está la respuesta" in html
    assert "¿Por qué no se paga la FA-1016?" in html and "¿Está pagado el pedido PO-2026-0474?" in html


def test_dice_la_verdad_de_cuando_estara(alberto):
    assert "Lo está preparando Fran; estará listo para el domingo." in preguntar(alberto)


def test_todavia_no_se_puede_escribir_ni_mandar_nada(alberto):
    html = preguntar(alberto)
    assert 'type="search" disabled' in html
    assert "Muy pronto: ¿cuánto vamos a pagar este mes?" in html
    assert "<form" not in html
