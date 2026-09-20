"""Preguntar: la pantalla del asistente (#39). El comportamiento del chat está en test_asistente."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def preguntar(alberto) -> str:
    respuesta = alberto.get(reverse("panel:preguntar"))
    assert respuesta.status_code == 200
    return respuesta.content.decode()


def test_explica_para_que_sirve_y_que_puede_preguntar(alberto):
    html = preguntar(alberto)
    assert "Pregunte lo que quiera" in html
    assert "nunca toco el ERP" in html
    assert "¿Por qué no se paga la FA-1016?" in html and "¿Está pagado el pedido PO-2026-0474?" in html


def test_se_puede_escribir_y_mandar(alberto):
    """El cuadro está activo y hay un formulario real que envía la pregunta."""
    html = preguntar(alberto)
    assert 'type="search" name="pregunta"' in html
    assert "disabled" not in html.split('name="pregunta"')[1].split(">")[0]  # el input no está deshabilitado
    assert "<form" in html and 'hx-post' in html
    assert "Pensando" in html  # el aviso de espera mientras la IA responde
