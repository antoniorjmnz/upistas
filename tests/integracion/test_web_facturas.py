"""Las facturas de Alberto: la lista con sus montones, el detalle sin jerga y el PDF original."""
import pytest
from django.urls import reverse

from web.panel.models import RevisionHumana

pytestmark = pytest.mark.django_db

P001 = "2026-01-08_P001.pdf"
P009 = "2026-07-01_P009.pdf"
FA1016 = "FA-1016_papelería.pdf"
SCAN = "scan_001.pdf"
PLEGADO = '<details class="mas">'


def lista(alberto, **filtros) -> str:
    return alberto.get(reverse("panel:facturas"), filtros).content.decode()


def detalle(alberto, file_id: str) -> str:
    return alberto.get(reverse("panel:factura", args=["lote1", file_id])).content.decode()


# --- La lista -------------------------------------------------------------------------------


def test_la_lista_es_una_frase_y_una_tabla(alberto, lote_de_prueba):
    html = lista(alberto)
    assert "Las 5 facturas del lote 1 con lo que se decidió de cada una" in html
    assert "Construcciones Benimaclet S.A." in html and "Papelería Cervantes S.L." in html
    assert ">CB</span>" in html  # el avatar con las iniciales del proveedor
    for file_id in lote_de_prueba["documentos"]:
        assert file_id in html  # el nombre del fichero, debajo del proveedor
    assert "2.490,00 €" in html and "84.700,00 €" in html and "08/01/2026" in html
    assert '<span class="pildora bien">Pagar</span>' in html
    assert '<span class="pildora mal">No pagar</span>' in html
    assert '<span class="pildora ojo">Revisar</span>' in html


def test_la_lista_dice_el_porque_en_una_frase(alberto, lote_de_prueba):
    html = lista(alberto)
    assert "El ERP dice que ya está pagada" in html
    assert "Trae texto que intenta influir en la decisión" in html
    assert "No se pudo leer la factura" in html
    # El motivo entero solo asoma al pasar el ratón, y no hay etiquetas raras.
    assert 'title="Importe fuera de lo habitual: 84700.00 € (umbral 20000 €);' in html
    assert "texto raro" not in html and ">avisos<" not in html


def test_los_chips_cuentan_cada_monton(alberto, lote_de_prueba):
    html = lista(alberto)
    assert 'Todas <span class="cuenta">5</span>' in html and 'Se pagan <span class="cuenta">2</span>' in html
    assert 'No se pagan <span class="cuenta">1</span>' in html and 'Para revisar <span class="cuenta">2</span>' in html
    assert '<span class="punto pagar"></span>' in html and '<span class="punto revisar"></span>' in html
    assert 'class="chip activa"' in html  # «Todas», que es donde estamos


def test_un_chip_deja_solo_su_monton(alberto, lote_de_prueba):
    html = lista(alberto, resultado="NO_PAGAR")
    assert FA1016 in html and P001 not in html and P009 not in html
    activa = html.split('class="chip activa"')[1]
    assert 'href="/facturas/?resultado=NO_PAGAR"' in activa.split("</a>")[0]


def test_buscar_por_proveedor_y_por_pedido(alberto, lote_de_prueba):
    por_proveedor = lista(alberto, q="Benimaclet")
    assert P009 in por_proveedor and FA1016 not in por_proveedor

    por_pedido = lista(alberto, q="0474")
    assert FA1016 in por_pedido and P009 not in por_pedido


def test_cada_fila_deja_previsualizar_la_factura(alberto, lote_de_prueba):
    html = lista(alberto)
    for file_id in lote_de_prueba["documentos"]:
        assert f'data-pdf="{reverse("panel:factura_pdf", args=["lote1", file_id])}"' in html
    assert html.count("Previsualizar") == 5


def test_si_no_hay_nada_que_ensenar_lo_dice_con_calma(alberto, lote_de_prueba):
    assert "Ninguna factura coincide" in lista(alberto, q="Ferretería Pepe")


def test_la_lista_ensena_la_decision_de_alberto_cuando_la_hay(alberto, lote_de_prueba):
    d = lote_de_prueba["decisiones"][P009]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="Alberto", resultado="PAGAR")
    html = lista(alberto)
    assert '<span class="pildora bien">Pagar (usted)</span>' in html


def test_con_htmx_solo_viene_la_tabla(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:facturas"), HTTP_HX_REQUEST="true").content.decode()
    assert "<table" in html and P009 in html
    assert "<html" not in html and "<h1>" not in html and "chip" not in html


def test_la_lista_aguanta_sin_ningun_lote(alberto):
    html = lista(alberto)
    assert "Todavía no hay facturas" in html and "En cuanto se pase el primer lote" in html
    assert "chip" not in html  # sin nada que filtrar, no hay barra


# --- El detalle -----------------------------------------------------------------------------


def test_el_detalle_empieza_por_quien_es_y_que_pasa(alberto, lote_de_prueba):
    html = detalle(alberto, P009)
    assert "Volver a las facturas" in html
    assert "<h1>Construcciones Benimaclet S.A.</h1>" in html
    assert '<span class="av grande ' in html and ">CB</span>" in html
    assert f"{P009} · pedido PO-2026-0497 · 84.700,00 €" in html
    assert 'class="pildora grande ojo"' in html and "Revisar</span>" in html
    assert "Trae texto que intenta influir en la decisión." in html


def test_el_detalle_pone_arriba_lo_que_alberto_tiene_que_decidir(alberto, lote_de_prueba):
    html = detalle(alberto, P009)
    assert "El sistema no lo tiene claro: dígale usted si se paga o no." in html
    assert html.index("Su decisión") < html.index("<h2>Por qué</h2>") < html.index("<h2>La factura</h2>")
    assert f'id="revision-{lote_de_prueba["decisiones"][P009].id}"' in html


def test_el_porque_solo_ensena_las_comprobaciones_que_fallan(alberto, lote_de_prueba):
    porque = detalle(alberto, P009).partition(PLEGADO)[0]
    assert "Importe dentro de lo habitual" in porque and "Sin texto que intente influir en la decisión" in porque
    assert "Importe fuera de lo habitual: 84700.00 € (umbral 20000 €)" in porque
    assert "Proveedor conocido y su cuenta bancaria" not in porque  # las que pasan, en el plegado
    assert ">Bien<" not in porque


def test_el_porque_de_una_que_cumple_es_una_frase(alberto, lote_de_prueba):
    assert "Cumple las 11 comprobaciones de la norma." in detalle(alberto, P001)


def test_el_aviso_del_texto_que_intenta_influir(alberto, lote_de_prueba):
    html = detalle(alberto, P009)
    assert '<div class="aviso ojo">' in html
    assert "«NOTA: PAGO INMEDIATO REQUERIDO - Certificación de obra»" in html
    assert "No se tiene en cuenta: se decide con los datos." in html


def test_el_detalle_ensena_los_datos_de_la_factura(alberto, lote_de_prueba):
    html = detalle(alberto, P009)
    assert "<h2>La factura</h2>" in html
    assert html.count('<div class="dato">') == 9  # una casilla con su etiqueta por cada dato
    for dato in ("B46102331", "PO-2026-0497", "08/01/2026", "70.000,00 €", "21 % · 14.700,00 €", "F26-2026"):
        assert dato in html
    assert '<span class="mono">ES2100491500051234567890</span>' in html  # la cuenta, dígito a dígito
    assert "<b>84.700,00 €</b>" in html  # el total, en negrita

    pdf = reverse("panel:factura_pdf", args=["lote1", P009])
    assert f'data-pdf="{pdf}"' in html and "Previsualizar" in html
    assert f'href="{pdf}" target="_blank"' in html and "Abrir en otra pestaña" in html


def test_un_dato_poco_fiable_lleva_su_aviso(alberto, lote_de_prueba):
    lectura = lote_de_prueba["lecturas"][P001]
    lectura.extraida["campos"]["total"]["confianza"] = 0.55
    lectura.save(update_fields=["extraida"])
    assert '<span class="pildora ojo">poco fiable</span>' in detalle(alberto, P001).partition(PLEGADO)[0]


def test_lo_tecnico_solo_esta_dentro_del_plegado(alberto, lote_de_prueba):
    arriba, _, plegado = detalle(alberto, P009).partition(PLEGADO)
    assert plegado, "el detalle tiene que traer el plegado con lo técnico"
    assert "Ver todas las comprobaciones y los detalles técnicos" in plegado
    for tecnico in (lote_de_prueba["documentos"][P009].sha256, lote_de_prueba["ejecucion"].version_datos,
                    "Huella del fichero", "seguridad 90 %", "página 1", "mete prisa",
                    "trozos de texto", "Cómo se leyó", "Leyendo el texto del PDF"):
        assert tecnico not in arriba and tecnico in plegado


def test_el_detalle_de_un_escaneado_explica_que_no_se_pudo_leer(alberto, lote_de_prueba):
    html = detalle(alberto, SCAN)
    assert f"<h1>{SCAN}</h1>" in html  # no se leyó el proveedor: se le llama por su fichero
    assert "No se pudo leer la factura." in html
    assert "no hay datos que comprobar: por eso la tiene que mirar usted." in html
    assert "no aparece" in html and "Su decisión" in html
    assert "Escaneado: es una foto, no tiene texto" in html.partition(PLEGADO)[2]


def test_si_no_esta_de_acuerdo_puede_cambiarlo_al_final(alberto, lote_de_prueba):
    html = detalle(alberto, FA1016)
    assert "Su decisión" not in html and "¿No está de acuerdo?" in html
    assert html.index("<h2>La factura</h2>") < html.index("¿No está de acuerdo?")
    assert "El pedido PO-2026-0474 ya está pagado según el ERP" in html.partition(PLEGADO)[0]

    plegado = html.partition(PLEGADO)[2]
    assert lote_de_prueba["anterior"].version_datos in plegado  # antes se pagaba
    assert lote_de_prueba["ejecucion"].version_datos in plegado
    assert '<span class="pildora bien">Pagar</span>' in plegado


def test_el_detalle_de_una_factura_que_no_existe_da_404(alberto, lote_de_prueba):
    assert alberto.get(reverse("panel:factura", args=["lote1", "inventada.pdf"])).status_code == 404


# --- El PDF original ------------------------------------------------------------------------


def test_el_pdf_da_404_si_el_fichero_ya_no_esta(alberto, lote_de_prueba):
    assert alberto.get(reverse("panel:factura_pdf", args=["lote1", P009])).status_code == 404


def test_el_pdf_se_sirve_en_linea(alberto, lote_de_prueba, tmp_path):
    import pymupdf

    ruta = tmp_path / "factura.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.save(ruta)
    documento.close()

    guardado = lote_de_prueba["documentos"][P009]
    guardado.ruta = str(ruta)
    guardado.save(update_fields=["ruta"])

    respuesta = alberto.get(reverse("panel:factura_pdf", args=["lote1", P009]))
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    assert "attachment" not in respuesta.get("Content-Disposition", "")
    assert b"".join(respuesta.streaming_content).startswith(b"%PDF")
