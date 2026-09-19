"""El historial de conversaciones del asistente (#39): se guardan en la base de datos, se siguen, se cambian
y se borran; las tres últimas salen en el menú lateral. Además, el proveedor de IA configurable y las
animaciones de «pensando». Sin red: la IA se sustituye por funciones que devuelven RespuestaModelo a mano."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from web.panel.asistente.agente import RespuestaModelo, SinCliente, responder
from web.panel.models import AccionAsistente, Conversacion, Pedido, Pregunta, Proveedor

pytestmark = pytest.mark.django_db

PREGUNTAR = reverse("panel:preguntar")


def _texto(t, **kw):
    return lambda mensajes, herramientas: RespuestaModelo(texto=t, **kw)


def _pregunta(alberto, texto, ruta="/"):
    return alberto.post(PREGUNTAR, {"pregunta": texto, "ruta": ruta}, HTTP_HX_REQUEST="true").content.decode()


@pytest.fixture
def ia(monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _texto("vale", modelo="glm5.3"))


def _panel(html: str) -> str:
    return html.split('id="asistente-conversacion"')[1].split("</dialog>")[0]


def _barra(html: str) -> str:
    return html.split('<aside class="lado">')[1].split("</aside>")[0]


# --- crear y seguir ---------------------------------------------------------------------------------


def test_la_primera_pregunta_crea_la_conversacion_y_le_da_titulo(alberto, ia):
    larga = "¿Por qué no se paga la factura FA-1016 de Papelería Cervantes que llegó la semana pasada con el pedido 474?"
    _pregunta(alberto, larga)
    c = Conversacion.objects.get()
    assert c.titulo == larga[:60] and len(c.titulo) == 60
    assert alberto.session["conversacion"] == c.pk
    p = Pregunta.objects.get()
    assert p.conversacion == c and p.texto == larga and p.respuesta == "vale" and p.modelo == "glm5.3"


def test_las_siguientes_preguntas_siguen_en_la_misma(alberto, ia):
    _pregunta(alberto, "una")
    _pregunta(alberto, "dos")
    c = Conversacion.objects.get()
    assert c.titulo == "una" and list(c.preguntas.order_by("id").values_list("texto", flat=True)) == ["una", "dos"]
    html = alberto.get(PREGUNTAR).content.decode()
    assert html.index("una") < html.index("dos")


def test_la_conversacion_se_reconstruye_desde_la_base_no_desde_la_sesion(alberto, ia):
    _pregunta(alberto, "una")
    sesion = alberto.session
    assert "chat" not in sesion  # ya no hay mensajes en la sesión
    Pregunta.objects.filter(texto="una").update(respuesta="cambiada en la base")
    assert "cambiada en la base" in alberto.get(PREGUNTAR).content.decode()


def test_la_sesion_no_pierde_la_actual_al_navegar(alberto, lote_de_prueba, ia):
    _pregunta(alberto, "¿cuántas se pagan?")
    c = Conversacion.objects.get()
    for url in (reverse("panel:inicio"), reverse("panel:facturas"), reverse("panel:cola"), reverse("panel:factura", args=["lote1", "scan_001.pdf"])):
        html = alberto.get(url).content.decode()
        assert alberto.session["conversacion"] == c.pk, url
        assert "¿cuántas se pagan?" in _panel(html) and "vale" in _panel(html), url
    _pregunta(alberto, "¿y de cuánto?", ruta=reverse("panel:facturas"))
    assert Conversacion.objects.count() == 1 and c.preguntas.count() == 2


def test_nueva_empieza_otra_y_la_anterior_se_queda(alberto, lote_de_prueba, ia):
    _pregunta(alberto, "primera")
    r = alberto.post(reverse("panel:asistente_nueva"), {"siguiente": reverse("panel:facturas")})
    assert r.status_code == 302 and r["Location"] == reverse("panel:facturas") + "#asistente"
    assert "conversacion" not in alberto.session
    assert "Aún no ha preguntado nada." in _panel(alberto.get(reverse("panel:facturas")).content.decode())
    _pregunta(alberto, "segunda")
    assert list(Conversacion.objects.values_list("titulo", flat=True)) == ["segunda", "primera"]  # la más reciente primero


def test_cambiar_a_otra_conversacion(alberto, lote_de_prueba, ia):
    _pregunta(alberto, "primera")
    primera = Conversacion.objects.get()
    alberto.post(reverse("panel:asistente_nueva"))
    _pregunta(alberto, "segunda")
    r = alberto.get(reverse("panel:asistente_abrir", args=[primera.pk]) + "?siguiente=" + reverse("panel:cola"))
    assert r.status_code == 302 and r["Location"] == reverse("panel:cola") + "#asistente"
    assert alberto.session["conversacion"] == primera.pk
    panel = _panel(alberto.get(reverse("panel:cola")).content.decode())
    assert "primera" in panel and "segunda" not in panel
    # desde la pantalla Preguntar se vuelve a ella sin #asistente (no hay panel encima)
    r = alberto.get(reverse("panel:asistente_abrir", args=[primera.pk]) + "?siguiente=" + PREGUNTAR)
    assert r["Location"] == PREGUNTAR
    assert alberto.get(reverse("panel:asistente_abrir", args=[9999])).status_code == 404


def test_seguir_una_conversacion_le_pasa_al_modelo_lo_anterior(alberto, monkeypatch):
    vistos = []

    def completar(mensajes, herramientas):
        vistos.append([m["content"] for m in mensajes if m["role"] in ("user", "assistant")])
        return RespuestaModelo(texto="vale")

    monkeypatch.setattr("web.panel.asistente.helmcode.completar", completar)
    _pregunta(alberto, "primera")
    c = Conversacion.objects.get()
    otro = Client()  # otra sesión (otro navegador) abre la misma conversación
    otro.get(reverse("panel:asistente_abrir", args=[c.pk]))
    otro.post(PREGUNTAR, {"pregunta": "sigo"}, HTTP_HX_REQUEST="true")
    assert vistos[-1] == ["primera", "vale", "sigo"]


def test_la_direccion_de_vuelta_solo_puede_ser_de_esta_web(alberto, ia):
    for mala in ("https://malo.example/", "//malo.example/x", "javascript:alert(1)", ""):
        r = alberto.post(reverse("panel:asistente_nueva"), {"siguiente": mala})
        assert r["Location"] == PREGUNTAR, mala


# --- borrar --------------------------------------------------------------------------------------------


def test_borrar_una_conversacion_borra_sus_preguntas_y_deja_las_acciones(alberto, ia):
    p = Proveedor.objects.create(codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331", iban="ES2100491500051234567890")
    Pedido.objects.create(numero="PO-2026-0001", proveedor=p, importe=2490)
    _pregunta(alberto, "marca el pedido 1")
    c = Conversacion.objects.get()
    from web.panel.asistente import acciones

    acciones.ejecutar("marcar_pedido_para_revisar", {"pedido": "PO-2026-0001"}, "nonce-1", c)
    assert "Hecho:" in alberto.get(PREGUNTAR).content.decode()  # la acción se enseña dentro de la conversación

    r = alberto.post(reverse("panel:asistente_borrar", args=[c.pk]), {"siguiente": reverse("panel:inicio")})
    assert r.status_code == 302 and r["Location"] == reverse("panel:inicio") + "#asistente"
    assert Conversacion.objects.count() == 0 and Pregunta.objects.count() == 0
    a = AccionAsistente.objects.get()
    assert a.conversacion is None and a.ok and Pedido.objects.get(numero="PO-2026-0001").revisar  # la traza se queda
    assert "conversacion" not in alberto.session  # era la abierta: la siguiente pregunta empieza otra
    assert alberto.post(reverse("panel:asistente_borrar", args=[c.pk])).status_code == 404


def test_borrar_otra_no_cambia_la_abierta(alberto, ia):
    _pregunta(alberto, "primera")
    primera = Conversacion.objects.get()
    alberto.post(reverse("panel:asistente_nueva"))
    _pregunta(alberto, "segunda")
    segunda = Conversacion.objects.get(titulo="segunda")
    alberto.post(reverse("panel:asistente_borrar", args=[primera.pk]))
    assert alberto.session["conversacion"] == segunda.pk and Conversacion.objects.count() == 1


def test_borrar_todas(alberto, ia):
    for i in range(3):
        _pregunta(alberto, f"conversación {i}")
        alberto.post(reverse("panel:asistente_nueva"))
    _pregunta(alberto, "la abierta")
    assert Conversacion.objects.count() == 4
    r = alberto.post(reverse("panel:asistente_borrar_todas"))
    assert r.status_code == 302 and r["Location"] == PREGUNTAR
    assert Conversacion.objects.count() == 0 and Pregunta.objects.count() == 0 and "conversacion" not in alberto.session


def test_borrar_exige_post_y_csrf(alberto, ia):
    _pregunta(alberto, "una")
    c = Conversacion.objects.get()
    estricto = Client(enforce_csrf_checks=True)
    for url in (reverse("panel:asistente_borrar", args=[c.pk]), reverse("panel:asistente_borrar_todas"), reverse("panel:asistente_nueva")):
        assert estricto.post(url).status_code == 403, url
        assert estricto.get(url).status_code == 405, url
    assert Conversacion.objects.count() == 1


# --- lo que se ve: la lista del panel y el menú lateral -------------------------------------------------


def test_el_panel_lleva_la_lista_con_nueva_papelera_y_borrar_todas(alberto, lote_de_prueba, ia):
    _pregunta(alberto, "primera")
    alberto.post(reverse("panel:asistente_nueva"))
    _pregunta(alberto, "segunda")
    html = alberto.get(reverse("panel:facturas")).content.decode()
    lista = html.split('<details class="conversaciones"')[1].split("</details>")[0]
    assert "<summary>" in lista and "Conversaciones" in lista and "(2)" in lista
    assert f'action="{reverse("panel:asistente_nueva")}"' in lista and "Nueva</button>" in lista
    assert "Borrar todas" in lista and f'action="{reverse("panel:asistente_borrar_todas")}"' in lista
    assert lista.count('class="papelera"') == 2 and "data-confirmar=" in lista and "csrfmiddlewaretoken" in lista
    assert lista.index("segunda") < lista.index("primera")  # la más reciente primero
    assert 'class="actual"' in lista and "hoy " in lista  # la abierta se distingue y lleva fecha corta
    for c in Conversacion.objects.all():
        assert reverse("panel:asistente_abrir", args=[c.pk]) in lista and reverse("panel:asistente_borrar", args=[c.pk]) in lista
    # en la pantalla Preguntar también, y «Ver todas» la deja abierta
    pagina = alberto.get(PREGUNTAR + "?lista=1").content.decode()
    assert '<details class="conversaciones" id="conversaciones" open>' in pagina
    assert '<details class="conversaciones" id="conversaciones">' in alberto.get(PREGUNTAR).content.decode()


def test_sin_conversaciones_la_lista_lo_dice_y_nueva_no_hace_falta(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:facturas")).content.decode()
    assert "Todavía no hay ninguna" in html and "Borrar todas" not in html
    assert "<div class=\"recientes\"" not in html  # y en el menú no sale nada


def test_la_barra_lateral_ensena_las_tres_ultimas(alberto, lote_de_prueba, ia):
    for i in range(1, 5):
        _pregunta(alberto, f"conversación número {i} que es bastante larga para recortarla")
        alberto.post(reverse("panel:asistente_nueva"))
    html = alberto.get(reverse("panel:facturas")).content.decode()
    barra = _barra(html)
    recientes = barra.split('<div class="recientes"')[1].split("</div>")[0]
    assert recientes.count('class="reciente') == 4  # tres conversaciones y «Ver todas»
    assert "número 4" in recientes and "número 3" in recientes and "número 2" in recientes and "número 1" not in recientes
    assert recientes.index("número 4") < recientes.index("número 3") < recientes.index("número 2")
    assert "…" in recientes  # el título va recortado
    assert "Ver todas" in recientes and PREGUNTAR + "?lista=1#conversaciones" in recientes
    c = Conversacion.objects.get(titulo__contains="número 4")
    assert reverse("panel:asistente_abrir", args=[c.pk]) + "?siguiente=" + reverse("panel:facturas") in recientes
    # la ruta de vuelta va codificada: lo que lleve detrás del «?» no rompe el enlace
    con_filtro = _barra(alberto.get(reverse("panel:facturas") + "?resultado=PAGAR&q=x").content.decode())
    assert "?siguiente=/facturas/%3Fresultado%3DPAGAR%26q%3Dx" in con_filtro
    # está debajo de «Preguntar», dentro del menú
    assert barra.index(">Preguntar</span>") < barra.index('<div class="recientes"') < barra.index('class="abajo"')


def test_con_tres_o_menos_no_hay_ver_todas_y_la_abierta_se_marca(alberto, lote_de_prueba, ia):
    _pregunta(alberto, "solo una")
    barra = _barra(alberto.get(reverse("panel:inicio")).content.decode())
    assert "Ver todas" not in barra and 'class="reciente actual"' in barra


def test_las_conversaciones_se_ven_en_el_admin():
    from django.contrib import admin

    assert Conversacion in admin.site._registry and "modelo" in admin.site._registry[Pregunta].list_display


# --- el proveedor de IA se configura en el .env -------------------------------------------------------------


@pytest.fixture
def config_recargada(monkeypatch):
    """Los ajustes se leen al importar config: se recarga con las variables puestas y se deja como estaba al salir."""
    import upistas.config as config

    def recargar(**variables):
        for nombre, valor in variables.items():
            monkeypatch.setenv(nombre, valor)
        importlib.reload(config)
        return config.settings

    yield recargar
    monkeypatch.undo()
    importlib.reload(config)


def test_los_ajustes_del_asistente_llegan_al_cliente(config_recargada, monkeypatch):
    from web.panel.asistente import helmcode

    ajustes = config_recargada(ASISTENTE_BASE_URL="https://openrouter.ai/api/v1", ASISTENTE_API_KEY="or-clave", ASISTENTE_MODELO="google/gemini-2.5-flash")
    assert (ajustes.asistente_base_url, ajustes.asistente_api_key, ajustes.asistente_modelo) == ("https://openrouter.ai/api/v1", "or-clave", "google/gemini-2.5-flash")
    assert ajustes.helmcode_base_url == "https://api.helmcode.com/v1"  # el pipeline de notas y visión no cambia

    vistos = {}

    class Completions:
        def create(self, **kw):
            vistos["modelo"] = kw["model"]
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "hola", "tool_calls": None})()})()], "usage": None, "model": "google/gemini-2.5-flash-001"})()

    class Cliente:
        chat = type("Chat", (), {"completions": Completions()})()

    def cliente_falso(api_key, base_url):
        vistos["clave"], vistos["url"] = api_key, base_url
        return Cliente()

    monkeypatch.setattr(helmcode, "_cliente", cliente_falso)
    r = helmcode.completar([{"role": "user", "content": "hola"}], [])
    assert vistos == {"clave": "or-clave", "url": "https://openrouter.ai/api/v1", "modelo": "google/gemini-2.5-flash"}
    assert r.texto == "hola" and r.modelo == "google/gemini-2.5-flash-001"  # se guarda el que contestó de verdad


def test_sin_ajustes_del_asistente_se_usa_helmcode(config_recargada, monkeypatch):
    for nombre in ("ASISTENTE_BASE_URL", "ASISTENTE_API_KEY", "ASISTENTE_MODELO"):
        monkeypatch.delenv(nombre, raising=False)
    ajustes = config_recargada(HELMCODE_API_KEY="hc-clave", HELMCODE_BASE_URL="https://api.helmcode.com/v1", MODELO_TEXTO="glm5.3")
    assert (ajustes.asistente_base_url, ajustes.asistente_api_key, ajustes.asistente_modelo) == ("https://api.helmcode.com/v1", "hc-clave", "glm5.3")


def test_sin_clave_del_asistente_ni_de_helmcode_se_avisa_como_siempre(config_recargada, monkeypatch):
    from web.panel.asistente import helmcode

    # Vacías, no borradas: el .env del repo las volvería a poner al recargar la configuración
    monkeypatch.setenv("ASISTENTE_API_KEY", "")
    monkeypatch.setenv("HELMCODE_API_KEY", "")
    ajustes = config_recargada()
    assert ajustes.asistente_api_key == ""
    with pytest.raises(SinCliente, match="ASISTENTE_API_KEY o HELMCODE_API_KEY"):
        helmcode.completar([{"role": "user", "content": "hola"}], [])
    r = responder("hola", [], helmcode.completar)
    assert not r.ok and "falta la clave" in r.texto and "sigue funcionando" in r.texto


def test_el_modelo_que_contesto_queda_en_la_pregunta(alberto, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _texto("vale", modelo="google/gemini-2.5-flash"))
    _pregunta(alberto, "una")
    assert Pregunta.objects.get().modelo == "google/gemini-2.5-flash"


def test_el_env_de_ejemplo_explica_openrouter():
    ejemplo = Path(".env.example").read_text(encoding="utf-8")
    assert "# ASISTENTE_BASE_URL=https://openrouter.ai/api/v1" in ejemplo
    assert "# ASISTENTE_API_KEY=" in ejemplo and "# ASISTENTE_MODELO=" in ejemplo


# --- animaciones: solo CSS, cortas, y apagadas si se pide menos movimiento ------------------------------------


def test_pensando_es_una_burbuja_del_asistente_con_tres_puntos(alberto, lote_de_prueba):
    for html in (alberto.get(PREGUNTAR).content.decode(), alberto.get(reverse("panel:facturas")).content.decode()):
        assert 'class="mensaje asistente pensando htmx-indicator" aria-hidden="true"><span class="puntos"><i></i><i></i><i></i></span>Pensando…' in html
        assert html.count("Pensando…") == 1  # el indicador es uno: no se duplica
        assert 'class="chat" aria-live="polite"' in html or 'class="chat asistente-chat" aria-live="polite"' in html
        assert 'hx-disabled-elt="find input, find button"' in html  # el botón se desactiva mientras espera y vuelve


def test_las_animaciones_son_cortas_y_se_apagan_con_reduced_motion():
    css = Path("web/panel/static/panel/panel.css").read_text(encoding="utf-8")
    assert ".pensando .puntos i { width: 6px; height: 6px; border-radius: 50%; background: var(--marca); animation: latir 600ms ease-out infinite alternate; }" in css
    assert "animation: brillo-pensando 600ms ease-out infinite alternate" in css
    assert ".chat .mensaje { transition: opacity 250ms ease-out, transform 250ms ease-out; }" in css
    assert ".chat .mensaje.htmx-added { opacity: 0; transform: translateY(4px); }" in css
    reducido = css.split("prefers-reduced-motion: reduce")[1]
    assert ".mensaje.pensando, .pensando .puntos i { animation: none; }" in reducido
    assert ".chat .mensaje, details.conversaciones summary svg { transition: none; }" in reducido
    assert ".chat .mensaje.htmx-added { opacity: 1; transform: none; }" in reducido
    js = Path("web/panel/static/panel/panel.js").read_text(encoding="utf-8")
    assert 'div.className = "mensaje alberto htmx-added"' in js  # la pregunta entra con el mismo fundido
    assert 'form[data-confirmar]' in js and "window.confirm" in js
