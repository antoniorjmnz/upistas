"""Lo común a todas las pantallas: sesión, consultas compartidas, filtros y el lote de prueba."""
import pytest
from django.urls import reverse

from web.panel import consultas
from web.panel.templatetags.panel_extras import campo, etiqueta, euros, pildora

pytestmark = pytest.mark.django_db


def test_el_lote_de_prueba_tiene_todos_los_casos(lote_de_prueba):
    decisiones = lote_de_prueba["decisiones"]
    assert {d.resultado for d in decisiones.values()} == {"PAGAR", "NO_PAGAR", "ESCALAR"}
    assert lote_de_prueba["ejecucion"].resumen["documentos"] == 5
    assert lote_de_prueba["lecturas"]["scan_001.pdf"].extraida is None  # el escaneado no se leyó
    assert decisiones["2026-07-01_P009.pdf"].notas[0]["categorias"] == ["urgencia"]


def test_consultas_compartidas(lote_de_prueba):
    actual, anterior = lote_de_prueba["ejecucion"], lote_de_prueba["anterior"]
    assert consultas.lotes() == ["lote1"]
    assert consultas.ultima_ejecucion() == actual and consultas.ultima_ejecucion("lote1") == actual
    assert consultas.anterior_a(actual) == anterior and consultas.anterior_a(anterior) is None
    assert {d.documento.file_id for d in consultas.pendientes_de_revision(actual)} == {"2026-07-01_P009.pdf", "scan_001.pdf"}
    previa, cambios = consultas.cambios_respecto_a_la_anterior(actual)
    assert previa == anterior and [(c.file_id, c.antes, c.despues) for c in cambios] == [("FA-1016_papelería.pdf", "PAGAR", "NO_PAGAR")]
    lectura = consultas.lecturas_por_sha([lote_de_prueba["documentos"]["2026-01-08_P001.pdf"].sha256]).popitem()[1]
    assert consultas.campos(lectura)["total"] == 2490.0 and consultas.campos(None) == {}


def test_la_revision_humana_saca_la_factura_de_pendientes(lote_de_prueba, django_user_model):
    from web.panel.models import RevisionHumana

    d = lote_de_prueba["decisiones"]["2026-07-01_P009.pdf"]
    RevisionHumana.objects.create(documento=d.documento, decision=d, quien="alberto", resultado="PAGAR", comentario="Obra certificada")
    pendientes = consultas.pendientes_de_revision(lote_de_prueba["ejecucion"])
    assert [p.documento.file_id for p in pendientes] == ["scan_001.pdf"]
    assert consultas.revisiones_por_documento("lote1")[d.documento_id].comentario == "Obra certificada"


def test_la_cabecera_cuenta_lo_pendiente_de_revisar(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:conexion")).content.decode()
    assert '<span class="insignia" title="Pendientes de revisar">2</span>' in html
    assert "Salir" in html and "alberto" in html


def test_filtros_de_plantilla():
    assert pildora("PAGAR") == "bien" and pildora("NO_PAGAR") == "mal" and pildora("ESCALAR") == "ojo" and pildora("?") == "neutra"
    assert etiqueta("ESCALAR") == "Revisar"
    assert euros(1234.5) == "1.234,50 €" and euros(None) == "" and euros("84700") == "84.700,00 €"
    assert campo({"campos": {"total": {"valor": 3}}}, "total") == 3 and campo(None, "total") is None


def test_el_comando_alberto_crea_el_usuario_una_vez(django_user_model):
    from django.core.management import call_command

    call_command("alberto")
    call_command("alberto")
    assert django_user_model.objects.filter(username="alberto").count() == 1
