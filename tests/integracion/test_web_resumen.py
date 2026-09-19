"""La portada: las cifras del lote, con qué datos se decidió, qué cambió y qué mirar primero."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_las_cifras_grandes_del_lote(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "<b>5</b><span>facturas repasadas</span>" in html
    assert "<b>2</b><span>para pagar</span>" in html
    assert "<b>1</b><span>para no pagar</span>" in html
    assert "<b>2</b><span>para mirar usted</span>" in html
    assert "0 ya revisadas · 2 sin mirar" in html
    assert "3.700,00 €" in html  # los dos PAGAR: 2.490,00 + 1.210,00
    assert "84.700,00 €" in html  # lo que está en el montón de revisar


def test_lo_que_alberto_ya_revisó_no_cuenta_como_pendiente(alberto, lote_de_prueba):
    from web.panel.models import RevisionHumana

    d = lote_de_prueba["decisiones"]["2026-07-01_P009.pdf"]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="alberto", resultado="PAGAR")
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "1 ya revisadas · 1 sin mirar" in html
    assert "2026-07-01_P009.pdf" not in html and "scan_001.pdf" in html


def test_con_que_datos_se_decidio(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert reverse("panel:asientos") + "?version=b189d7434436" in html  # la copia del ERP que se usó
    assert "d7729db76ec7" in html  # la versión del Excel
    assert "38,5 segundos" in html and "0,1 facturas por segundo" in html
    assert "0,00 €" in html  # lo que costó la inteligencia artificial
    assert "4 de 5 salieron del propio texto del PDF" in html
    assert "1 no se pudieron leer" in html


def test_que_ha_cambiado_desde_la_vez_anterior(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "<b>1</b> factura con otro resultado." in html
    assert reverse("panel:factura", args=["lote1", "FA-1016_papelería.pdf"]) in html
    assert 'pasa de</span> <span class="pildora bien">Pagar</span>' in html
    assert '<span class="pildora mal">No pagar</span>' in html
    assert reverse("panel:ejecucion", args=[lote_de_prueba["ejecucion"].id]) in html


def test_lo_primero_que_tiene_que_mirar(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "Importe fuera de lo habitual" in html
    assert reverse("panel:factura", args=["lote1", "2026-07-01_P009.pdf"]) in html
    assert reverse("panel:factura", args=["lote1", "scan_001.pdf"]) in html
    assert "Ir a la cola de revisión (2 sin mirar)" in html
    assert reverse("panel:cola") in html


def test_sin_ninguna_ejecucion_lo_explica_con_calma(alberto):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "Todavía no se ha repasado ningún lote de facturas." in html
    assert "uv run upistas run" in html
    assert "facturas repasadas" not in html


def test_avisa_si_el_erp_no_respondio_y_dice_con_que_copia_seguimos(alberto, lote_de_prueba):
    from web.panel.models import SincronizacionERP, VersionERP

    ahora = timezone.now()
    version = VersionERP.objects.create(version="b189d7434436", creada=ahora - timedelta(hours=3), n_asientos=516)
    SincronizacionERP.objects.create(
        inicio=ahora - timedelta(hours=3), fin=ahora - timedelta(hours=3), ok=True, version=version, n_asientos=516,
    )
    SincronizacionERP.objects.create(inicio=ahora, fin=ahora, ok=False, error="El ERP no responde")

    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "El ERP no respondió" in html and "Seguimos con la copia del" in html
    assert "no se ha perdido nada" in html


def test_el_selector_de_lote_solo_sale_con_varios_lotes(alberto, lote_de_prueba):
    from web.panel.models import Ejecucion

    assert "?lote=lote1" not in alberto.get(reverse("panel:inicio")).content.decode()

    ahora = timezone.now()
    Ejecucion.objects.create(
        lote="lote2", norma="v4", version_erp="c0ffeec0ffee", version_excel="d7729db76ec7",
        inicio=ahora, fin=ahora + timedelta(seconds=80), estado="terminada",
        resumen={"documentos": 40, "PAGAR": 30, "NO_PAGAR": 5, "ESCALAR": 5, "leidos": 40, "segundos": 80.0,
                 "por_metodo": {"texto_determinista": 40}},
    )
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "Lote 1" in html and "Lote 2" in html
    assert "<b>40</b><span>facturas repasadas</span>" in html  # sin pedir nada, el lote más reciente

    del_lote1 = alberto.get(reverse("panel:inicio"), {"lote": "lote1"}).content.decode()
    assert "<b>5</b><span>facturas repasadas</span>" in del_lote1
