"""El asistente en la barra lateral (#39): panel en todas las pantallas, contexto, «Ir a» y acciones
con confirmación. Sin red: la IA se sustituye por funciones que devuelven RespuestaModelo a mano."""
import json
from datetime import timedelta

import pytest
from django.core import signing
from django.urls import reverse

from web.panel.asistente import acciones
from web.panel.asistente.agente import SISTEMA, Llamada, RespuestaModelo, frase_de_contexto, responder
from web.panel.asistente.herramientas import HERRAMIENTAS, ejecutar
from web.panel.asistente.navegacion import ir_a
from web.panel.models import AccionAsistente, Pedido, Proveedor, RevisionHumana
from web.panel.views.chat import MAX_MENSAJES, contexto_de

pytestmark = pytest.mark.django_db


def _texto(t):
    return lambda mensajes, herramientas: RespuestaModelo(texto=t)


def _pide(nombre, argumentos, despues="Listo"):
    llamadas = [RespuestaModelo(llamadas=(Llamada("call_1", nombre, json.dumps(argumentos)),)), RespuestaModelo(texto=despues)]
    return lambda mensajes, herramientas: llamadas.pop(0)


@pytest.fixture
def maestro(db):
    p = Proveedor.objects.create(codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331", iban="ES2100491500051234567890")
    Pedido.objects.create(numero="PO-2026-0001", proveedor=p, importe=2490)
    Pedido.objects.create(numero="PO-2026-0497", proveedor=p, importe=84700, revisar=True)
    return p


# --- el panel está en todas las pantallas --------------------------------------------------------


def test_el_panel_esta_en_todas_las_pantallas(alberto, lote_de_prueba, maestro):
    for url in (reverse("panel:inicio"), reverse("panel:facturas"), reverse("panel:cola"), reverse("panel:proveedores"),
                reverse("panel:proveedor", args=[maestro.id]), reverse("panel:factura", args=["lote1", "scan_001.pdf"]),
                reverse("panel:ejecuciones"), reverse("panel:conexion"), reverse("panel:preguntar")):
        html = alberto.get(url).content.decode()
        assert '<dialog id="asistente" class="asistente"' in html, url
        assert 'data-abrir-asistente' in html and "Pensando" in html, url
        assert f'name="ruta" value="{url}"' in html, url  # el panel sabe en qué pantalla está


# --- contexto: «esta factura» es la de la pantalla --------------------------------------------------


def test_contexto_de_una_ruta_de_la_web(maestro):
    c = contexto_de("/facturas/lote1/scan_001.pdf/?x=1")
    assert c["pantalla"] == "factura" and c["lote"] == "lote1" and c["file_id"] == "scan_001.pdf"
    c = contexto_de(reverse("panel:proveedor", args=[maestro.id]))
    assert c["pantalla"] == "proveedor" and c["proveedor"] == "Suministros Levante S.L. (P001)"
    assert contexto_de("/no-existe/") is None and contexto_de("https://otra.web/") is None
    assert contexto_de("//otra.web/facturas/") is None and contexto_de("") is None and contexto_de("/admin/") is None


def test_la_frase_de_contexto_habla_de_la_pantalla():
    assert frase_de_contexto({"pantalla": "factura", "lote": "lote1", "file_id": "scan_001.pdf", "ruta": "/facturas/lote1/scan_001.pdf/"}) == (
        "Alberto está ahora en el detalle de la factura scan_001.pdf (lote lote1) (ruta /facturas/lote1/scan_001.pdf/)."
    )
    assert frase_de_contexto({"pantalla": "cola"}) == "Alberto está ahora en Para revisar."
    assert frase_de_contexto({"pantalla": "factura"}) == "Alberto está ahora en el detalle de la factura."  # sin los datos
    assert frase_de_contexto(None) == "" and frase_de_contexto({}) == ""


def test_la_pregunta_con_contexto_llega_al_agente(alberto, lote_de_prueba, monkeypatch):
    vistos = []

    def completar(mensajes, herramientas):
        vistos.append(mensajes[0]["content"])
        return RespuestaModelo(texto="Es la escaneada")

    monkeypatch.setattr("web.panel.asistente.helmcode.completar", completar)
    r = alberto.post(reverse("panel:preguntar"), {"pregunta": "¿por qué no se paga esta factura?", "ruta": "/facturas/lote1/scan_001.pdf/"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "Es la escaneada" in r.content.decode()
    assert vistos[0].startswith(SISTEMA) and "detalle de la factura scan_001.pdf (lote lote1)" in vistos[0]
    assert "esta factura" in SISTEMA  # el sistema le dice qué significa


def test_sin_contexto_el_sistema_va_tal_cual(lote_de_prueba):
    vistos = []

    def completar(mensajes, herramientas):
        vistos.append(mensajes[0]["content"])
        return RespuestaModelo(texto="vale")

    responder("hola", [], completar)
    responder("hola", [], completar, {"ruta": "/x/"})  # sin pantalla no se inventa nada
    assert vistos == [SISTEMA, SISTEMA]


# --- ir_a: siempre a una pantalla de la web ----------------------------------------------------------


def test_ir_a_devuelve_rutas_de_la_web_y_nunca_otras(lote_de_prueba, maestro):
    assert ir_a("facturas", {"resultado": "NO_PAGAR"}) == {"url": reverse("panel:facturas") + "?resultado=NO_PAGAR", "titulo": "Facturas · No pagar"}
    assert ir_a("facturas", {"proveedor": "levante", "desde": "2026-01-01", "hasta": "2026-03-31"}) == {
        "url": reverse("panel:facturas") + "?proveedor=P001&desde=2026-01-01&hasta=2026-03-31", "titulo": "Facturas de Suministros Levante S.L.",
    }
    assert ir_a("revisar", {"resultado": "PAGAR", "texto": "obra"})["url"] == reverse("panel:cola") + "?q=obra"
    assert ir_a("factura", {"file_id": "scan_001.pdf"}) == {"url": reverse("panel:factura", args=["lote1", "scan_001.pdf"]), "titulo": "Factura scan_001.pdf"}
    assert ir_a("proveedor", {"proveedor": "B46102331"}) == {"url": reverse("panel:proveedor", args=[maestro.id]), "titulo": "Suministros Levante S.L."}
    assert ir_a("asientos", {"pedido": "PO-2026-0474"})["url"] == reverse("panel:asientos") + "?q=PO-2026-0474"
    for pantalla, nombre in (("inicio", "panel:inicio"), ("proveedores", "panel:proveedores"), ("ejecuciones", "panel:ejecuciones"), ("erp", "panel:conexion")):
        assert ir_a(pantalla)["url"] == reverse(nombre)

    for salida in (ir_a("facturas", {"texto": "https://malo.example/x", "proveedor": "//malo"}), ir_a("asientos", {"pedido": "http://x"})):
        assert salida["url"].startswith("/") and not salida["url"].startswith("//") and "http" not in salida["url"].split("?")[0]
    assert "error" in ir_a("https://malo.example") and "error" in ir_a("factura", {}) and "error" in ir_a("factura", {"file_id": "nada.pdf"})
    assert "error" in ir_a("proveedor", {"proveedor": "Nadie"})


def test_ir_a_avisa_de_los_filtros_que_no_valen(lote_de_prueba, maestro):
    salida = ir_a("facturas", {"resultado": "MAL", "proveedor": "Nadie", "desde": "ayer"})
    assert salida["url"] == reverse("panel:facturas") and len(salida["avisos"]) == 3


def test_ir_a_sale_como_boton_en_la_respuesta(alberto, lote_de_prueba, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _pide("ir_a", {"pantalla": "revisar"}, "Ahí las tiene"))
    html = alberto.post(reverse("panel:preguntar"), {"pregunta": "llévame a lo que hay que revisar"}, HTTP_HX_REQUEST="true").content.decode()
    assert f'class="boton pequeno" href="{reverse("panel:cola")}">Ir a Para revisar' in html


def test_las_herramientas_nuevas_estan_declaradas():
    nombres = [h["function"]["name"] for h in HERRAMIENTAS]
    assert "ir_a" in nombres and "proponer_accion" in nombres
    assert ejecutar("ir_a", {"pantalla": "inicio"})["datos"]["url"] == reverse("panel:inicio")


# --- acciones: proponer no cambia nada; confirmar sí, y queda registrado ----------------------------


def test_proponer_no_cambia_nada(maestro):
    r = acciones.proponer("marcar_pedido_para_revisar", {"pedido": "PO-2026-0001"})
    assert r["propuesta"]["datos"] == {"pedido": "PO-2026-0001"} and "token" in r["propuesta"]
    assert r["propuesta"]["descripcion"] == "Marcar el pedido PO-2026-0001 para que sus facturas se revisen a mano"
    assert not Pedido.objects.get(numero="PO-2026-0001").revisar and AccionAsistente.objects.count() == 0


def test_proponer_rechaza_lo_que_no_esta_en_la_lista(maestro, lote_de_prueba):
    assert "no existe" in acciones.proponer("pagar_factura", {"file_id": "scan_001.pdf"})["error"]
    assert "no existe" in acciones.proponer("borrar_proveedor", {"proveedor": "P001"})["error"]
    assert "no está en el maestro" in acciones.proponer("marcar_pedido_para_revisar", {"pedido": "PO-2026-9999"})["error"]
    assert "falta" in acciones.proponer("apuntar_nota_en_pedido", {"pedido": "PO-2026-0001"})["error"]
    assert "solo se comentan las escaladas" in acciones.proponer("apuntar_comentario_en_factura", {"file_id": "2026-01-08_P001.pdf", "comentario": "x"})["error"]
    assert "no está en el último repaso" in acciones.proponer("apuntar_comentario_en_factura", {"file_id": "nada.pdf", "comentario": "x"})["error"]
    assert "pagar" in SISTEMA and "prohibido" in SISTEMA


def test_la_propuesta_sale_como_tarjeta_y_no_se_ejecuta(alberto, maestro, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar",
                        _pide("proponer_accion", {"tipo": "marcar_pedido_para_revisar", "datos": {"pedido": "PO-2026-0001"}}, "Se lo propongo"))
    html = alberto.post(reverse("panel:preguntar"), {"pregunta": "marca el pedido 1 para revisar"}, HTTP_HX_REQUEST="true").content.decode()
    assert "El asistente propone:" in html and "Marcar el pedido PO-2026-0001" in html
    assert 'name="token"' in html and ">Confirmar</button>" in html and ">No</button>" in html
    assert f'hx-post="{reverse("panel:asistente_accion")}"' in html
    assert not Pedido.objects.get(numero="PO-2026-0001").revisar and AccionAsistente.objects.count() == 0


def test_confirmar_ejecuta_y_registra(alberto, maestro):
    token = acciones.proponer("marcar_pedido_para_revisar", {"pedido": "PO-2026-0001"})["propuesta"]["token"]
    html = alberto.post(reverse("panel:asistente_accion"), {"token": token}, HTTP_HX_REQUEST="true").content.decode()
    assert "Hecho:" in html and "PO-2026-0001 queda marcado para revisar" in html
    assert f'href="{reverse("panel:proveedor", args=[maestro.id])}"' in html
    assert Pedido.objects.get(numero="PO-2026-0001").revisar
    a = AccionAsistente.objects.get()
    assert a.tipo == "marcar_pedido_para_revisar" and a.datos == {"pedido": "PO-2026-0001"} and a.ok
    # queda al pie de la conversación y la tarjeta ya no se puede confirmar otra vez
    pagina = alberto.get(reverse("panel:preguntar")).content.decode()
    assert "Hecho:" in pagina and "El asistente propone" not in pagina


def test_las_otras_acciones(alberto, maestro, lote_de_prueba):
    token = acciones.proponer("quitar_marca_de_pedido", {"pedido": "PO-2026-0497"})["propuesta"]["token"]
    alberto.post(reverse("panel:asistente_accion"), {"token": token})
    assert not Pedido.objects.get(numero="PO-2026-0497").revisar

    token = acciones.proponer("apuntar_nota_en_pedido", {"pedido": "PO-2026-0497", "nota": "Certificación de obra"})["propuesta"]["token"]
    alberto.post(reverse("panel:asistente_accion"), {"token": token})
    assert Pedido.objects.get(numero="PO-2026-0497").nota == "Certificación de obra"

    token = acciones.proponer("apuntar_comentario_en_factura", {"file_id": "2026-07-01_P009.pdf", "comentario": "Llamar al proveedor"})["propuesta"]["token"]
    alberto.post(reverse("panel:asistente_accion"), {"token": token})
    assert RevisionHumana.objects.count() == 0  # comentar no es decidir: sigue pendiente de revisar
    html = alberto.get(reverse("panel:factura", args=["lote1", "2026-07-01_P009.pdf"])).content.decode()
    assert "Comentarios que apuntó desde Preguntar" in html and "«Llamar al proveedor»" in html
    assert AccionAsistente.objects.filter(ok=True).count() == 3


def test_token_caducado_o_manipulado_no_hace_nada(alberto, maestro, monkeypatch):
    token = acciones.proponer("marcar_pedido_para_revisar", {"pedido": "PO-2026-0001"})["propuesta"]["token"]
    html = alberto.post(reverse("panel:asistente_accion"), {"token": token[:-3] + "xyz"}, HTTP_HX_REQUEST="true").content.decode()
    assert "no es válida" in html
    html = alberto.post(reverse("panel:asistente_accion"), {"token": ""}, HTTP_HX_REQUEST="true").content.decode()
    assert "no es válida" in html

    import time as _time

    ahora = _time.time()
    monkeypatch.setattr("django.core.signing.time.time", lambda: ahora + acciones.CADUCIDAD_S + 1)
    html = alberto.post(reverse("panel:asistente_accion"), {"token": token}, HTTP_HX_REQUEST="true").content.decode()
    assert "ha caducado" in html
    assert not Pedido.objects.get(numero="PO-2026-0001").revisar and AccionAsistente.objects.count() == 0


def test_un_tipo_fuera_de_la_lista_se_rechaza_aunque_venga_firmado(alberto, maestro, lote_de_prueba):
    for tipo, datos in (("pagar_factura", {"file_id": "2026-07-01_P009.pdf"}), ("borrar_pedido", {"pedido": "PO-2026-0001"})):
        token = signing.dumps({"tipo": tipo, "datos": datos}, salt="asistente.accion")
        html = alberto.post(reverse("panel:asistente_accion"), {"token": token}, HTTP_HX_REQUEST="true").content.decode()
        assert "no es válida" in html
    with pytest.raises(acciones.AccionInvalida):
        acciones.ejecutar("pagar_factura", {"file_id": "2026-07-01_P009.pdf"})
    assert AccionAsistente.objects.count() == 0 and RevisionHumana.objects.count() == 0 and Pedido.objects.count() == 2


def test_confirmar_algo_que_ya_no_existe_queda_como_fallido(alberto, maestro):
    token = acciones.proponer("apuntar_nota_en_pedido", {"pedido": "PO-2026-0001", "nota": "x"})["propuesta"]["token"]
    Pedido.objects.filter(numero="PO-2026-0001").delete()
    html = alberto.post(reverse("panel:asistente_accion"), {"token": token}, HTTP_HX_REQUEST="true").content.decode()
    assert "No se pudo" in html and not AccionAsistente.objects.get().ok


def test_confirmar_exige_post_y_csrf(maestro):
    from django.test import Client

    token = acciones.proponer("marcar_pedido_para_revisar", {"pedido": "PO-2026-0001"})["propuesta"]["token"]
    estricto = Client(enforce_csrf_checks=True)
    assert estricto.post(reverse("panel:asistente_accion"), {"token": token}).status_code == 403
    assert estricto.get(reverse("panel:asistente_accion")).status_code == 405
    assert not Pedido.objects.get(numero="PO-2026-0001").revisar


def test_las_acciones_se_ven_en_el_admin():
    from django.contrib import admin

    assert AccionAsistente in admin.site._registry


# --- la conversación sobrevive a cambiar de pantalla -------------------------------------------------


def test_la_conversacion_sigue_al_cambiar_de_pantalla(alberto, lote_de_prueba, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _texto("Se paga una"))
    alberto.post(reverse("panel:preguntar"), {"pregunta": "¿cuántas se pagan?", "ruta": "/"}, HTTP_HX_REQUEST="true")
    for url in (reverse("panel:facturas"), reverse("panel:cola"), reverse("panel:factura", args=["lote1", "scan_001.pdf"])):
        html = alberto.get(url).content.decode()
        panel = html.split('id="asistente-conversacion"')[1]
        assert "¿cuántas se pagan?" in panel and "Se paga una" in panel, url


def test_la_conversacion_tiene_tope(alberto, lote_de_prueba, monkeypatch):
    monkeypatch.setattr("web.panel.asistente.helmcode.completar", _texto("vale"))
    for i in range(MAX_MENSAJES):
        alberto.post(reverse("panel:preguntar"), {"pregunta": f"pregunta {i}"}, HTTP_HX_REQUEST="true")
    assert len(alberto.session["chat"]) == MAX_MENSAJES == 20
    assert alberto.session["chat"][0]["texto"] == f"pregunta {MAX_MENSAJES // 2}"


def test_el_panel_tiene_transicion_corta_y_respeta_reduced_motion():
    from pathlib import Path

    css = Path("web/panel/static/panel/panel.css").read_text(encoding="utf-8")
    assert "dialog.asistente[open] { transform: translateX(0)" in css and "220ms" in css
    reducido = css.split("prefers-reduced-motion: reduce")[1]
    assert "dialog.asistente[open]" in reducido
    assert "@media (max-width: 640px) { dialog.asistente { width: 100vw" in css


def test_el_pedido_se_encuentra_con_cualquier_forma_de_escribirlo(maestro):
    for como in ("PO-2026-0497", "po 2026 497", "497", "0497"):
        assert acciones.proponer("marcar_pedido_para_revisar", {"pedido": como})["propuesta"]["datos"] == {"pedido": "PO-2026-0497"}


def test_la_caducidad_es_de_diez_minutos():
    assert acciones.CADUCIDAD_S == timedelta(minutes=10).total_seconds()
