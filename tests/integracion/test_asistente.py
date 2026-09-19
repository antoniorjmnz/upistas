"""El asistente de «Preguntar»: herramientas sobre datos de prueba y bucle con un LLM falso.

Nada de red: `completar` se sustituye por funciones que devuelven RespuestaModelo a mano.
"""
import json
from dataclasses import replace
from decimal import Decimal

import pytest
from django.urls import reverse

from tests.integracion.conftest import ASIENTOS, ClienteFalso
from web.panel.asistente.agente import MENSAJE_FUERA_DE_TEMA, SISTEMA, Llamada, RespuestaModelo, responder
from web.panel.asistente.herramientas import ejecutar
from web.panel import consultas
from web.panel.models import RevisionHumana

pytestmark = pytest.mark.django_db


def _texto(t, **kw):
    return lambda mensajes, herramientas: RespuestaModelo(texto=t, **kw)


def _pide(nombre, argumentos, despues):
    """Una IA falsa: primero pide la herramienta, luego responde."""
    llamadas = [RespuestaModelo(llamadas=(Llamada("call_1", nombre, json.dumps(argumentos)),), tokens_in=10, tokens_out=2), despues]
    return lambda mensajes, herramientas: llamadas.pop(0)


# --- consultas (las herramientas, sin IA) -----------------------------------------------------


def test_resumen_del_lote(lote_asistente):
    r = consultas.resumen_lote()
    assert r["facturas"] == 3 and r["pagar"] == 1 and r["no_pagar"] == 1 and r["escalar"] == 1
    assert r["importe_a_pagar"] == pytest.approx(859.40)
    assert r["norma"] == "v3"


def test_resumen_sin_ejecuciones():
    assert "aviso" in consultas.resumen_lote()


def test_buscar_por_numero_de_factura(lote_asistente):
    r = consultas.buscar_facturas("FA-1016")
    assert [f["file_id"] for f in r["encontradas"]] == ["factura_pagada.pdf"]


def test_buscar_por_pedido_suelto(lote_asistente):
    r = consultas.buscar_facturas("474")
    assert any(f["file_id"] == "factura_pagada.pdf" for f in r["encontradas"])


def test_detalle_explica_la_decision(lote_asistente):
    d = consultas.detalle_factura("factura_pagada.pdf")
    assert d["decision"]["resultado"] == "NO_PAGAR"
    assert "pagado" in d["decision"]["motivo"]
    assert d["reglas"][0]["id"] == "R5_erp_estado"
    assert d["lectura"]["campos"]["numero_factura"] == "FA-1016"


def test_detalle_desconocida_sugiere_parecidas(lote_asistente):
    d = consultas.detalle_factura("pagada")
    assert "aviso" in d and "factura_pagada.pdf" in d["parecidas"]


def test_pendientes_y_revisada(lote_asistente):
    assert consultas.pendientes_revision()["cuantas"] == 1
    RevisionHumana.objects.create(
        documento_id=lote_asistente.decisiones.get(resultado="ESCALAR").documento_id,
        quien="Alberto", resultado="NO_PAGAR",
    )
    assert consultas.pendientes_revision()["cuantas"] == 0


def test_estado_pedido_acepta_solo_digitos(copia_erp):
    r = consultas.estado_pedido("474")
    assert r["pedido"] == "PO-2026-0474" and r["estado_erp"] == "PAGADA" and r["asiento"] == "AS-00474"


def test_estado_pedido_con_decision(lote_asistente):
    r = consultas.estado_pedido("PO-2026-0474")
    assert r["decision_nuestra"]["file_id"] == "factura_pagada.pdf"


def test_estado_pedido_inexistente(copia_erp):
    assert "aviso" in consultas.estado_pedido("PO-2026-9999")


def test_cambios_entre_dos_versiones(copia_erp):
    from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
    from upistas.aplicacion.sincronizar_erp import sincronizar_erp

    otros = (ASIENTOS[0], replace(ASIENTOS[1], estado="PENDIENTE"))
    sincronizar_erp(ClienteFalso(otros), AlmacenERPDjango())
    r = consultas.cambios_erp()
    assert r["de"] != r["a"]
    assert any(c["asiento"] == "AS-00474" and c["campo"] == "estado" for c in r["modificados"])
    assert "AS-00507" in r["eliminados"]


def test_cambios_sin_dos_versiones(copia_erp):
    assert "aviso" in consultas.cambios_erp()


def test_ejecutar_herramienta_desconocida_y_argumentos_mal():
    assert "error" in ejecutar("volar", {})
    assert "error" in ejecutar("resumen_lote", "{no es json")


# --- el bucle del agente con IA falsa ---------------------------------------------------------


def test_respuesta_directa_sin_herramientas(lote_asistente):
    r = responder("hola", [], _texto("Hola Alberto", tokens_in=3, tokens_out=1))
    assert r.texto == "Hola Alberto" and r.ok and r.tokens_in == 3


def test_el_modelo_pide_herramienta_y_redacta(lote_asistente):
    completar = _pide("resumen_lote", {}, RespuestaModelo(texto="Se pagan 1 por 859,40 €", tokens_in=50, tokens_out=8))
    r = responder("¿cuántas se pagan?", [], completar)
    assert "859" in r.texto and r.tokens_in == 60


def test_las_fuentes_enlazan_a_la_pantalla(copia_erp):
    completar = _pide("estado_pedido", {"pedido": "474"}, RespuestaModelo(texto="Está pagado"))
    r = responder("¿está pagado el pedido 474?", [], completar)
    assert r.fuentes and "asientos" in r.fuentes[0]["url"] and "PO-2026-0474" in r.fuentes[0]["url"]


def test_si_la_ia_falla_la_web_sigue(lote_asistente):
    def rota(mensajes, herramientas):
        raise ConnectionError("Helmcode no responde")

    r = responder("algo", [], rota)
    assert not r.ok and "no responde" in r.texto


def test_historial_se_pasa_al_modelo(lote_asistente):
    vistos = []

    def completar(mensajes, herramientas):
        vistos.extend(m["role"] for m in mensajes)
        return RespuestaModelo(texto="vale")

    responder("y de cuánto?", [{"quien": "alberto", "texto": "cuántas se pagan"}, {"quien": "asistente", "texto": "una"}], completar)
    assert vistos[:3] == ["system", "user", "assistant"]


def test_no_responde_sobre_codigo():
    """Lo que no es de facturas se rechaza sin llamar a la IA: gratis y determinista."""
    def prohibido(mensajes, herramientas):
        raise AssertionError("la IA no debería llamarse")

    for pregunta in ["escríbeme un programa en Python", "depura este código",
                     "cómo hago una página web", "qué es una API", "arregla este bug"]:
        r = responder(pregunta, [], prohibido)
        assert r.texto == MENSAJE_FUERA_DE_TEMA and r.tokens_in == 0


def test_las_facturas_no_disparan_el_filtro():
    """Preguntas legítimas con palabras parecidas sí llegan a la IA."""
    def ok(mensajes, herramientas):
        return RespuestaModelo(texto="vale")

    for pregunta in ["¿cuánto suman las facturas del lote?", "¿qué ha cambiado desde la última vez?"]:
        assert responder(pregunta, [], ok).texto == "vale"


def test_el_prompt_tambien_acota_el_tema():
    """Si el filtro no pilla algo ajeno, la IA debe responder con el mismo mensaje."""
    assert MENSAJE_FUERA_DE_TEMA in SISTEMA


# --- la pantalla -------------------------------------------------------------------------------


def test_preguntar_get(alberto):
    r = alberto.get(reverse("panel:preguntar"))
    assert r.status_code == 200 and "Preguntar" in r.content.decode()


def test_preguntar_post_guarda_la_pregunta_y_su_coste(alberto, lote_asistente, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _texto("Se paga una", tokens_in=12, tokens_out=4))
    r = alberto.post(reverse("panel:preguntar"), {"pregunta": "¿cuántas se pagan?"}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert r.status_code == 200 and "<html" not in html  # fragmento para htmx
    assert "Se paga una" in html

    from web.panel.models import Pregunta

    p = Pregunta.objects.get()
    assert p.texto == "¿cuántas se pagan?" and p.tokens_in == 12 and p.ok


def test_la_conversacion_se_queda_en_la_sesion(alberto, lote_asistente, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _texto("respuesta"))
    alberto.post(reverse("panel:preguntar"), {"pregunta": "una cosa"})
    html = alberto.get(reverse("panel:preguntar")).content.decode()
    assert "una cosa" in html and "respuesta" in html
