"""Las ejecuciones: la lista de repasos, el detalle de uno y el outcomes.jsonl que se entrega."""
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_la_lista_ensena_las_cifras_de_cada_repaso(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:ejecuciones")).content.decode()
    assert html.count("Terminado") == 2  # las dos pasadas del lote de prueba
    assert "Lote 1" in html
    assert "b189d7434436+d7729db76ec7" in html  # con qué copia de los datos se decidió
    assert "38,5 s" in html and "0,1" in html
    assert reverse("panel:ejecucion", args=[lote_de_prueba["ejecucion"].id]) in html


def test_la_lista_incluye_las_que_no_han_terminado(alberto, lote_de_prueba):
    from web.panel.models import Ejecucion

    Ejecucion.objects.create(lote="lote1", norma="v3", inicio=timezone.now(), estado="en_curso")
    html = alberto.get(reverse("panel:ejecuciones")).content.decode()
    assert "En marcha" in html


def test_el_detalle_explica_cifras_hardware_datos_y_cambios(alberto, lote_de_prueba):
    ejecucion = lote_de_prueba["ejecucion"]
    html = alberto.get(reverse("panel:ejecucion", args=[ejecucion.id])).content.decode()
    assert "<b>5</b><span>facturas repasadas</span>" in html
    assert "<b>2</b><span>para pagar</span>" in html
    assert "Windows" in html and "AMD64" in html and "3.12.6" in html  # el ordenador donde se hizo
    assert reverse("panel:asientos") + "?version=b189d7434436" in html
    assert "d7729db76ec7" in html
    assert "<b>1</b> factura con otro resultado." in html
    assert reverse("panel:factura", args=["lote1", "FA-1016_papelería.pdf"]) in html
    assert reverse("panel:outcomes", args=[ejecucion.id]) in html


def test_el_primer_repaso_no_tiene_con_que_compararse(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:ejecucion", args=[lote_de_prueba["anterior"].id])).content.decode()
    assert "Es el primer repaso de este lote" in html


def test_una_ejecucion_que_no_existe_da_404(alberto, lote_de_prueba):
    assert alberto.get(reverse("panel:ejecucion", args=[9999])).status_code == 404


def test_el_outcomes_jsonl_es_una_linea_por_factura(alberto, lote_de_prueba):
    ejecucion = lote_de_prueba["ejecucion"]
    r = alberto.get(reverse("panel:outcomes", args=[ejecucion.id]))
    assert r.status_code == 200
    assert r["Content-Type"] == "application/x-ndjson; charset=utf-8"
    assert r["Content-Disposition"] == 'attachment; filename="outcomes.jsonl"'

    cuerpo = r.content.decode("utf-8")
    lineas = cuerpo.splitlines()
    assert len(lineas) == 5
    outcomes = [json.loads(linea) for linea in lineas]
    assert all(o["result"] in ("PAGAR", "NO_PAGAR", "ESCALAR") for o in outcomes)
    assert [o["file_id"] for o in outcomes] == sorted(o["file_id"] for o in outcomes)
    assert "papelería" in cuerpo  # los acentos van tal cual, sin escapar
    assert outcomes[3] == lote_de_prueba["decisiones"]["FA-1016_papelería.pdf"].outcome


def test_el_fichero_de_otro_lote_lleva_el_lote_en_el_nombre(alberto, lote_de_prueba):
    from web.panel.models import Ejecucion

    ahora = timezone.now()
    otro = Ejecucion.objects.create(
        lote="lote2", norma="v4", inicio=ahora, fin=ahora + timedelta(seconds=1), estado="terminada",
    )
    r = alberto.get(reverse("panel:outcomes", args=[otro.id]))
    assert r["Content-Disposition"] == 'attachment; filename="outcomes_lote2.jsonl"'
    assert r.content == b""
