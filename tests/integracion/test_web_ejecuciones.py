"""El registro de repasos: la lista, el detalle de un repaso y el outcomes.jsonl que se entrega."""
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def registro(alberto) -> str:
    return alberto.get(reverse("panel:ejecuciones")).content.decode()


def repaso(alberto, ejecucion) -> str:
    return alberto.get(reverse("panel:ejecucion", args=[ejecucion.id])).content.decode()


def test_el_registro_ensena_cada_repaso_en_una_linea(alberto, lote_de_prueba):
    html = registro(alberto)
    assert "Cada vez que el sistema repasa un lote queda apuntado aquí" in html
    assert html.count("Terminado") == 2  # las dos pasadas del lote de prueba
    assert "Lote 1" in html and "38,5 s" in html
    assert reverse("panel:ejecucion", args=[lote_de_prueba["ejecucion"].id]) in html


def test_el_registro_no_ensena_lo_tecnico(alberto, lote_de_prueba):
    html = registro(alberto)
    for tecnico in ("tokens", "b189d7434436", "coste", "por segundo", "€"):
        assert tecnico not in html  # los tokens, el coste y la versión de los datos van en el detalle


def test_el_registro_vacio_lo_dice_con_calma(alberto):
    html = registro(alberto)
    assert "Todavía no se ha repasado ningún lote" in html and "<table" not in html


def test_el_registro_incluye_los_repasos_que_no_han_terminado(alberto, lote_de_prueba):
    from web.panel.models import Ejecucion

    Ejecucion.objects.create(lote="lote1", norma="v3", inicio=timezone.now(), estado="en_curso")
    assert "En marcha" in registro(alberto)


def test_el_detalle_cuenta_el_repaso_en_una_frase_y_cuatro_cifras(alberto, lote_de_prueba):
    html = repaso(alberto, lote_de_prueba["ejecucion"])
    assert "Volver al registro" in html
    assert "<b>5</b> facturas del lote 1" in html
    assert "<b>2</b> se pueden pagar" in html and "<b>1</b> no," in html and "<b>2</b> esperan su decisión" in html
    assert "<b>5</b><span>facturas repasadas</span>" in html
    assert "<b>2</b><span>se pagan</span>" in html
    assert "<b>1</b><span>no se pagan</span>" in html
    assert "<b>2</b><span>para revisar</span>" in html


def test_el_detalle_ensena_que_cambio_y_el_fichero_de_resultados(alberto, lote_de_prueba):
    ejecucion = lote_de_prueba["ejecucion"]
    html = repaso(alberto, ejecucion)
    assert "Qué cambió respecto al repaso anterior" in html
    assert "<b>1</b> factura cambia de resultado" in html
    assert reverse("panel:factura", args=["lote1", "FA-1016_papelería.pdf"]) in html
    assert '<span class="pildora mal">No pagar</span>' in html and "antes pagar" in html
    assert "Descargar el fichero de resultados" in html
    assert reverse("panel:outcomes", args=[ejecucion.id]) in html


def test_el_detalle_pliega_lo_tecnico_en_detalles(alberto, lote_de_prueba):
    arriba, _, tecnico = repaso(alberto, lote_de_prueba["ejecucion"]).partition("<details")
    assert "Detalles técnicos" in tecnico
    for dato in ("b189d7434436", "d7729db76ec7", "tokens", "facturas por segundo", "Windows", "AMD64", "3.12.6"):
        assert dato not in arriba and dato in tecnico  # nada de esto se ve sin desplegar
    assert reverse("panel:asientos") + "?version=b189d7434436" in tecnico


def test_el_primer_repaso_no_tiene_con_que_compararse(alberto, lote_de_prueba):
    assert "Es el primer repaso de este lote" in repaso(alberto, lote_de_prueba["anterior"])


def test_un_repaso_que_no_existe_da_404(alberto, lote_de_prueba):
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
