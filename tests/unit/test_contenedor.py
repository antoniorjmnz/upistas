from dataclasses import replace

import pytest

from upistas.adaptadores.lectores.vision_helmcode import VisionHelmcode
from upistas.infra import contenedor


@pytest.fixture
def ajustes():
    original = contenedor.settings
    yield original
    contenedor.configurar(original)


def test_el_timeout_de_vision_llega_al_adaptador(ajustes):
    contenedor.configurar(replace(ajustes, usar_ocr=True, helmcode_api_key="clave-de-prueba", vision_timeout_s=7))
    vision = contenedor.lectores()[0].vision
    assert isinstance(vision, VisionHelmcode)
    assert vision.cliente.timeout == 7


@pytest.mark.parametrize("segundos", [0, -1, float("inf"), float("nan")])
def test_timeout_de_vision_invalido_se_rechaza(ajustes, segundos):
    with pytest.raises(ValueError, match="VISION_TIMEOUT_S"):
        contenedor.configurar(replace(ajustes, vision_timeout_s=segundos))
    assert contenedor.settings is ajustes
