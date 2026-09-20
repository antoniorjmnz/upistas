"""El asistente llega a todo lo que enseña la web (#39): listados acotados con `total` y `mas`, ficha del
proveedor, decisiones de Alberto, repasos, importaciones, reglas explicadas e `ir_a` con lote e Importar datos.
Sin red: la IA se sustituye por funciones que devuelven RespuestaModelo a mano."""
import json
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse

from web.panel import consultas
from web.panel.asistente import acciones
from web.panel.asistente.agente import SISTEMA, Llamada, RespuestaModelo, responder
from web.panel.asistente.herramientas import HERRAMIENTAS, _FUNCIONES, ejecutar
from web.panel.asistente.navegacion import ir_a
from web.panel.models import AccionAsistente, Importacion, Pedido, Proveedor, RevisionHumana

pytestmark = pytest.mark.django_db

NORMA_V3 = Path(__file__).resolve().parents[2] / "normas" / "v3.toml"


def _pide(nombre, argumentos, despues="Listo"):
    llamadas = [RespuestaModelo(llamadas=(Llamada("call_1", nombre, json.dumps(argumentos)),)), RespuestaModelo(texto=despues)]
    return lambda mensajes, herramientas: llamadas.pop(0)


@pytest.fixture
def maestro(db):
    p = Proveedor.objects.create(codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331",
                                 iban="ES21 0049 1500 0512 3456 7890", ciudad="Valencia", condiciones_dias=60)
    Pedido.objects.create(numero="PO-2026-0001", proveedor=p, importe=Decimal("2490.00"))
    Pedido.objects.create(numero="PO-2026-0497", proveedor=p, importe=Decimal("84700.00"), revisar=True, nota="Llamar antes de pagar")
    Pedido.objects.create(numero="PO-2026-0301", proveedor=p, importe=Decimal("1210.00"), nota="Suele venir en dos partes")
    Proveedor.objects.create(codigo="P003", nombre="Ofimática Cieza S.L.", nif="B30455812", iban="ES6001825322180201588391")
    return p


# --- 1) listados con limite, total y mas -------------------------------------------------------------


def test_buscar_facturas_acota_y_dice_cuantas_quedan(lote_asistente):
    r = consultas.buscar_facturas("factura_", limite=2)
    assert len(r["encontradas"]) == 2 and r["total"] == 3 and r["mas"] == 1
    todas = consultas.buscar_facturas("factura_", limite=100)
    assert len(todas["encontradas"]) == 3 and todas["mas"] == 0


def test_el_limite_va_de_uno_a_cien_y_si_no_es_un_numero_se_ignora():
    assert consultas.acotar_limite(500, 10) == consultas.LIMITE_MAXIMO == 100
    assert consultas.acotar_limite(0, 10) == 1 and consultas.acotar_limite(-3, 10) == 1
    assert consultas.acotar_limite("40", 10) == 40
    assert consultas.acotar_limite("todas", 10) == 10 and consultas.acotar_limite(None, 15) == 15


def test_el_modelo_puede_pedir_mas_filas_por_la_herramienta(lote_asistente):
    corto = ejecutar("buscar_facturas", {"texto": "factura_", "limite": 1})["datos"]
    assert len(corto["encontradas"]) == 1 and corto["mas"] == 2
    largo = ejecutar("buscar_facturas", json.dumps({"texto": "factura_", "limite": 40}))["datos"]
    assert len(largo["encontradas"]) == 3 and largo["mas"] == 0
    pendientes = ejecutar("pendientes_revision", {"limite": 1})["datos"]
    assert len(pendientes["pendientes"]) == 1 and pendientes["total"] == 1 and pendientes["mas"] == 0


def test_el_sistema_dice_como_tratar_las_listas_largas():
    assert "total y mas" in SISTEMA and "ir_a" in SISTEMA and "«todas»" in SISTEMA and "hasta 100" in SISTEMA
    for h in HERRAMIENTAS:
        f = h["function"]
        if f["name"] in ("buscar_facturas", "pendientes_revision", "decisiones_de_alberto", "repasos", "importaciones"):
            assert f["parameters"]["properties"]["limite"]["type"] == "integer", f["name"]


# --- 2) herramientas nuevas de solo lectura ----------------------------------------------------------


def test_ficha_del_proveedor_por_codigo_nif_o_nombre(maestro):
    r = consultas.proveedor("P001")
    assert r["nombre"] == "Suministros Levante S.L." and r["nif"] == "B46102331" and r["dias_de_pago"] == 60
    assert r["iban"] == "…7890" and "ES2100491500051234567890" not in json.dumps(r)
    assert r["pedidos"] == 3 and r["importe_pedidos"] == pytest.approx(88400.0)
    assert r["marcados_para_revisar"] == [{"numero": "PO-2026-0497", "importe": 84700.0, "fecha": None, "marcado_para_revisar": True, "nota": "Llamar antes de pagar"}]
    assert [p["numero"] for p in r["con_nota"]] == ["PO-2026-0301"]
    assert consultas.proveedor("b46102331")["codigo"] == "P001"
    assert consultas.proveedor("levante")["codigo"] == "P001"
    assert consultas.proveedor("cieza")["marcados_para_revisar"] == []


def test_proveedor_desconocido_avisa_y_sugiere(maestro):
    r = consultas.proveedor("Suministros del Norte")
    assert "aviso" in r and r["parecidos"] == []
    assert consultas.proveedor("S.L.")["codigo"] in ("P001", "P003")  # varios: el primero por nombre
    assert "aviso" in consultas.proveedor("")


def test_decisiones_de_alberto(lote_asistente):
    escalada = lote_asistente.decisiones.get(resultado="ESCALAR")
    RevisionHumana.objects.create(documento_id=escalada.documento_id, decision=escalada, quien="Alberto",
                                  resultado="NO_PAGAR", comentario="Que manden la factura rectificada")
    pagada = lote_asistente.decisiones.get(resultado="NO_PAGAR")
    RevisionHumana.objects.create(documento_id=pagada.documento_id, decision=pagada, quien="Alberto", resultado="PAGAR")

    r = consultas.decisiones_de_alberto()
    assert r["total"] == 2 and r["mas"] == 0
    assert [d["file_id"] for d in r["decisiones"]] == ["factura_pagada.pdf", "factura_rara.pdf"]  # la más reciente primero
    rara = r["decisiones"][1]
    assert rara["decidio"] == "NO_PAGAR" and rara["comentario"] == "Que manden la factura rectificada" and rara["lote"] == "lote1"
    assert r["decisiones"][0]["comentario"] is None and rara["cuando"]

    assert consultas.decisiones_de_alberto(limite=1)["mas"] == 1
    assert consultas.decisiones_de_alberto(lote="lote9")["total"] == 0
    assert ejecutar("decisiones_de_alberto", {"lote": "lote1", "limite": 5})["datos"]["total"] == 2


def test_repasos_con_sus_cifras_y_lo_que_cambio(lote_de_prueba):
    r = consultas.repasos()
    assert r["total"] == 2 and r["mas"] == 0
    actual, anterior = r["repasos"]
    assert actual["lote"] == "lote1" and actual["norma"] == "v3" and actual["segundos"] == 38.5
    assert (actual["pagar"], actual["no_pagar"], actual["escalar"]) == (2, 1, 2)
    assert actual["cambios_respecto_al_anterior"]["cuantos"] == 1
    assert actual["cambios_respecto_al_anterior"]["primeros"] == [{"file_id": "FA-1016_papelería.pdf", "antes": "PAGAR", "despues": "NO_PAGAR"}]
    assert anterior["cambios_respecto_al_anterior"] is None  # no hay otro antes
    assert consultas.repasos(limite=1)["mas"] == 1
    assert "aviso" not in ejecutar("repasos", {})["datos"]


def test_los_cambios_entre_repasos_coinciden_con_la_comparacion_de_la_pantalla(lote_de_prueba):
    _, cambios = consultas.cambios_respecto_a_la_anterior(lote_de_prueba["ejecucion"])
    baratos = consultas._cambios_baratos(lote_de_prueba["ejecucion"])["primeros"]
    assert [(c.file_id, c.antes, c.despues) for c in cambios] == [(c["file_id"], c["antes"], c["despues"]) for c in baratos]


def test_importaciones():
    assert consultas.importaciones() == {"importaciones": [], "total": 0, "mas": 0}
    for i in range(3):
        Importacion.objects.create(ficheros=f"pedidos_{i}.csv", nuevos=i, cambiados=1, invalidos=0)
    r = consultas.importaciones(limite=2)
    assert r["total"] == 3 and r["mas"] == 1 and r["importaciones"][0]["ficheros"] == "pedidos_2.csv"
    assert r["importaciones"][0] == {"cuando": r["importaciones"][0]["cuando"], "ficheros": "pedidos_2.csv", "nuevos": 2, "cambiados": 1, "invalidos": 0}
    assert ejecutar("importaciones", {"limite": 10})["datos"]["mas"] == 0


def test_las_herramientas_nuevas_enlazan_a_su_pantalla(maestro, lote_de_prueba):
    RevisionHumana.objects.create(documento=lote_de_prueba["documentos"]["scan_001.pdf"], quien="Alberto", resultado="PAGAR")
    Importacion.objects.create(ficheros="proveedores.csv", nuevos=1)
    esperado = [
        ("proveedor", {"proveedor": "levante"}, {"titulo": "Proveedor Suministros Levante S.L.", "url": reverse("panel:proveedor", args=[maestro.id])}),
        ("decisiones_de_alberto", {}, {"titulo": "Facturas decididas", "url": reverse("panel:cola") + "?estado=decididas"}),
        ("repasos", {}, {"titulo": "Registro de repasos", "url": reverse("panel:ejecuciones")}),
        ("importaciones", {}, {"titulo": "Importar datos", "url": reverse("panel:proveedor_importar")}),
    ]
    for herramienta, args, fuente in esperado:
        r = responder("¿qué hay?", [], _pide(herramienta, args))
        assert r.fuentes == [fuente], herramienta
    assert responder("¿?", [], _pide("proveedor", {"proveedor": "nadie"})).fuentes == []


# --- 3) explicar el porqué sin una factura delante ---------------------------------------------------


def test_cada_regla_de_la_norma_tiene_explicacion_llana():
    reglas = tomllib.loads(NORMA_V3.read_text(encoding="utf-8"))["reglas"]
    assert set(reglas) <= set(consultas.EXPLICACION_REGLA)
    for id_regla, conf in reglas.items():
        ficha = consultas.explicar_regla(id_regla)["regla"]
        assert ficha["si_falla"] == {"NO_PAGAR": "no se paga", "ESCALAR": "se manda a revisar"}[conf["si_falla"]], id_regla
        assert ficha["comprueba"] and ficha["por_que"] and "aviso" not in ficha
    assert set(consultas.MOTIVO_CORTO) <= set(consultas.EXPLICACION_REGLA)  # todo lo que sale en una lista se puede explicar


def test_explicar_regla_por_palabra_numero_o_id():
    [r1] = consultas.explicar_regla("iban")["reglas"]
    assert r1["id"] == "R1_nif_iban" and r1["si_falla"] == "no se paga" and "cuenta" in r1["por_que"]
    assert r1["nombre"] == consultas.NOMBRE_REGLA["R1_nif_iban"] and r1["en_una_frase"] == consultas.MOTIVO_CORTO["R1_nif_iban"]
    assert [r["id"] for r in consultas.explicar_regla("regla 2")["reglas"]] == ["R2_pedido_importe"]
    cinco = [r["id"] for r in consultas.explicar_regla("R5")["reglas"]]
    assert "R5_no_pagada" in cinco and "R5_erp_pendiente" in cinco
    assert consultas.explicar_regla("R6_notas")["regla"]["si_falla"] == "se manda a revisar"
    assert "aviso" in consultas.explicar_regla("R9_destinatario")["regla"]  # fuera de la norma en uso, pero explicada


def test_explicar_regla_sin_argumento_o_desconocida_da_el_flujo_y_la_lista():
    todo = consultas.explicar_regla()
    assert todo["flujo"] == consultas.RESUMEN_FLUJO and {r["id"] for r in todo["reglas"]} >= {"R1_nif_iban", "R0_lectura", "R5_no_pagada"}
    raro = consultas.explicar_regla("la regla del pijama")
    assert "aviso" in raro and raro["reglas"] == todo["reglas"]
    assert ejecutar("explicar_regla", {"regla": "notas"})["datos"]["reglas"][0]["id"] == "R6_notas"
    assert "flujo" in ejecutar("explicar_regla", {})["datos"]


def test_el_sistema_lleva_el_flujo_en_pocas_palabras():
    assert consultas.RESUMEN_FLUJO in SISTEMA and "explicar_regla" in SISTEMA
    assert len(consultas.RESUMEN_FLUJO.split()) < 120
    assert "no pagar antes que revisar" in consultas.RESUMEN_FLUJO


# --- 4) ir_a con lote e Importar datos --------------------------------------------------------------


def test_ir_a_filtra_por_lote_y_llega_a_importar(lote_de_prueba):
    assert ir_a("facturas", {"lote": "lote1"}) == {"url": reverse("panel:facturas") + "?lote=lote1", "titulo": "Facturas · Lote 1"}
    assert ir_a("revisar", {"lote": "Lote 1", "texto": "obra"})["url"] == reverse("panel:cola") + "?q=obra&lote=lote1"
    con_aviso = ir_a("facturas", {"lote": "lote9"})
    assert con_aviso["url"] == reverse("panel:facturas") and "lote9" in con_aviso["avisos"][0] and "lote1" in con_aviso["avisos"][0]
    assert ir_a("importar") == {"url": reverse("panel:proveedor_importar"), "titulo": "Importar datos"}
    assert ejecutar("ir_a", {"pantalla": "importar"})["datos"]["url"] == reverse("panel:proveedor_importar")


# --- nada de escritura fuera de la lista ------------------------------------------------------------


def test_todas_las_herramientas_declaradas_existen_y_al_reves():
    declaradas = {h["function"]["name"] for h in HERRAMIENTAS}
    assert declaradas == set(_FUNCIONES)
    assert {"proveedor", "decisiones_de_alberto", "repasos", "importaciones", "explicar_regla"} <= declaradas


def test_las_herramientas_nuevas_no_escriben_nada(maestro, lote_de_prueba):
    RevisionHumana.objects.create(documento=lote_de_prueba["documentos"]["scan_001.pdf"], quien="Alberto", resultado="PAGAR")
    antes = (RevisionHumana.objects.count(), AccionAsistente.objects.count(), Pedido.objects.filter(revisar=True).count(), Proveedor.objects.count())
    for nombre, args in (("proveedor", {"proveedor": "P001"}), ("decisiones_de_alberto", {"limite": 50}), ("repasos", {}),
                         ("importaciones", {}), ("explicar_regla", {"regla": "iban"}), ("buscar_facturas", {"texto": "pdf", "limite": 100}),
                         ("pendientes_revision", {"limite": 100}), ("ir_a", {"pantalla": "importar"})):
        assert "error" not in ejecutar(nombre, args), nombre
    assert (RevisionHumana.objects.count(), AccionAsistente.objects.count(), Pedido.objects.filter(revisar=True).count(), Proveedor.objects.count()) == antes


def test_el_sistema_sigue_sin_permitir_acciones_fuera_de_la_lista(maestro, lote_de_prueba):
    [propone] = [h for h in HERRAMIENTAS if h["function"]["name"] == "proponer_accion"]
    assert set(propone["function"]["parameters"]["properties"]["tipo"]["enum"]) == set(acciones.TIPOS) == {
        "marcar_pedido_para_revisar", "quitar_marca_de_pedido", "apuntar_nota_en_pedido", "apuntar_comentario_en_factura",
    }
    for tipo in ("pagar_factura", "importar_datos", "repasar_lote", "borrar_proveedor"):
        assert "no existe" in ejecutar("proponer_accion", {"tipo": tipo, "datos": {}})["datos"]["error"], tipo
    assert "error" in ejecutar("importar", {}) and "error" in ejecutar("revisar_factura", {"file_id": "scan_001.pdf"})
    assert "prohibido" in SISTEMA and "pagar o no pagar una factura" in SISTEMA and AccionAsistente.objects.count() == 0
