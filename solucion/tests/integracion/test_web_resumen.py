"""La portada (Hoy): una frase, tres montones, lo que hay que mirar y qué cambió."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def portada(alberto, **filtros) -> str:
    return alberto.get(reverse("panel:inicio"), filtros).content.decode()


def test_una_frase_y_tres_montones(alberto, lote_de_prueba):
    html = portada(alberto)
    assert "<b>5</b> facturas del lote 1" in html and "<b>2</b> se pueden pagar" in html and "<b>2</b> esperan su decisión" in html
    assert '<span class="n">2</span>' in html and '<span class="n">1</span>' in html
    assert "3.700,00 € en total" in html  # los dos PAGAR: 2.490,00 + 1.210,00
    assert "84.700,00 € en juego" in html  # lo que está en el montón de revisar
    assert reverse("panel:facturas") + "?resultado=PAGAR" in html and reverse("panel:cola") in html


def test_lo_que_alberto_ya_decidio_no_cuenta_como_pendiente(alberto, lote_de_prueba):
    from web.panel.models import RevisionHumana

    d = lote_de_prueba["decisiones"]["2026-07-01_P009.pdf"]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="Alberto", resultado="PAGAR")
    html = portada(alberto)
    assert "<b>1</b> esperan su decisión" in html and "1 ya decidida" in html
    assert "2026-07-01_P009.pdf" not in html and "scan_001.pdf" in html


def test_lo_primero_que_tiene_que_mirar(alberto, lote_de_prueba):
    html = portada(alberto)
    assert "Lo que tiene que mirar" in html
    assert "Construcciones Benimaclet S.A." in html and "84.700,00 €" in html  # quién es y cuánto pide
    assert "Trae texto que intenta influir en la decisión" in html and "No se pudo leer la factura" in html
    assert reverse("panel:factura", args=["lote1", "2026-07-01_P009.pdf"]) in html
    assert reverse("panel:factura", args=["lote1", "scan_001.pdf"]) in html
    assert "Empezar a revisar" in html


def test_cuando_no_queda_nada_lo_celebra(alberto, lote_de_prueba):
    from web.panel.models import RevisionHumana

    for fid in ("2026-07-01_P009.pdf", "scan_001.pdf"):
        d = lote_de_prueba["decisiones"][fid]
        RevisionHumana.objects.create(documento=d.documento, decision=d, quien="Alberto", resultado="NO_PAGAR")
    html = portada(alberto)
    assert "No le queda nada por decidir" in html and "Empezar a revisar" not in html


def test_que_ha_cambiado_desde_el_repaso_anterior(alberto, lote_de_prueba):
    html = portada(alberto)
    assert "Desde el repaso anterior, 1 factura cambia de resultado" in html
    assert reverse("panel:factura", args=["lote1", "FA-1016_papelería.pdf"]) in html
    assert '<span class="pildora mal">No pagar</span>' in html and "antes pagar" in html


def test_dice_cuando_y_con_que_se_decidio_sin_agobiar(alberto, lote_de_prueba):
    html = portada(alberto)
    assert "con la copia del ERP de ese momento y la versión 3 de la norma" in html
    assert reverse("panel:ejecucion", args=[lote_de_prueba["ejecucion"].id]) in html
    assert "tokens" not in html and "b189d7434436" not in html  # lo técnico no va en la portada


def test_sin_ninguna_ejecucion_lo_explica_con_calma(alberto):
    html = portada(alberto)
    assert "Todavía no hay facturas repasadas" in html and "uv run upistas run" in html
    assert "se pueden pagar" not in html


def test_avisa_si_el_erp_no_respondio_y_dice_con_que_copia_seguimos(alberto, lote_de_prueba):
    from web.panel.models import SincronizacionERP, VersionERP

    ahora = timezone.now()
    version = VersionERP.objects.create(version="b189d7434436", creada=ahora - timedelta(hours=3), n_asientos=516)
    SincronizacionERP.objects.create(
        inicio=ahora - timedelta(hours=3), fin=ahora - timedelta(hours=3), ok=True, version=version, n_asientos=516,
    )
    SincronizacionERP.objects.create(inicio=ahora, fin=ahora, ok=False, error="El ERP no responde")
    html = portada(alberto)
    assert "El ERP no respondió" in html and "no se ha perdido nada" in html


def test_con_varios_lotes_ensena_el_mas_reciente_y_deja_pedir_otro(alberto, lote_de_prueba):
    from web.panel.models import Ejecucion

    ahora = timezone.now()
    Ejecucion.objects.create(
        lote="lote2", norma="v4", version_erp="c0ffeec0ffee", version_excel="d7729db76ec7",
        inicio=ahora, fin=ahora + timedelta(seconds=80), estado="terminada",
        resumen={"documentos": 40, "PAGAR": 30, "NO_PAGAR": 5, "ESCALAR": 5, "leidos": 40, "segundos": 80.0,
                 "por_metodo": {"texto_determinista": 40}},
    )
    assert "<b>40</b> facturas del lote 2" in portada(alberto)
    assert "<b>5</b> facturas del lote 1" in portada(alberto, lote="lote1")
