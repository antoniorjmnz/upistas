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
    assert "Registro de repasos" in html  # el pie, para quien lleva el sistema


def test_filtros_de_plantilla():
    assert pildora("PAGAR") == "bien" and pildora("NO_PAGAR") == "mal" and pildora("ESCALAR") == "ojo" and pildora("?") == "neutra"
    assert etiqueta("ESCALAR") == "Revisar"
    assert euros(1234.5) == "1.234,50 €" and euros(None) == "" and euros("84700") == "84.700,00 €"
    assert campo({"campos": {"total": {"valor": 3}}}, "total") == 3 and campo(None, "total") is None


def test_el_motivo_corto_habla_como_alberto(lote_de_prueba):
    d = lote_de_prueba["decisiones"]
    assert consultas.motivo_corto(d["FA-1016_papelería.pdf"]) == "El ERP dice que ya está pagada"
    assert consultas.motivo_corto(d["2026-07-01_P009.pdf"]) == "Trae texto que intenta influir en la decisión"
    assert consultas.motivo_corto(d["scan_001.pdf"]) == "No se pudo leer la factura"
    assert consultas.motivo_corto(d["2026-01-08_P001.pdf"]) == "Cumple la norma"


def test_iniciales_y_color_del_avatar():
    from web.panel.templatetags.panel_extras import color_avatar, iniciales

    assert iniciales("Construcciones Benimaclet S.A.") == "CB" and iniciales("Limpiezas Turia S.L.") == "LT"
    assert iniciales("Suministros Levante S.L.") == "SL" and iniciales(None) == "?"
    assert color_avatar("Limpiezas Turia S.L.") in "abcdef" and color_avatar("Limpiezas Turia S.L.") == color_avatar("Limpiezas Turia S.L.")


def test_la_barra_lateral_dice_como_esta_el_erp(alberto, lote_de_prueba):
    from django.utils import timezone

    from web.panel.models import SincronizacionERP

    assert "ERP: todavía sin copia" in alberto.get(reverse("panel:inicio")).content.decode()
    ahora = timezone.now()
    SincronizacionERP.objects.create(inicio=ahora, fin=ahora, ok=True, n_asientos=516)
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert "ERP al día" in html and 'class="estado-erp bien"' in html
    SincronizacionERP.objects.create(inicio=ahora, fin=ahora, ok=False, error="ORA-00600")
    assert 'class="estado-erp mal"' in alberto.get(reverse("panel:inicio")).content.decode()


def test_previsualizar_abre_el_pdf_encima_de_la_pagina(alberto, lote_de_prueba):
    html = alberto.get(reverse("panel:inicio")).content.decode()
    assert 'data-pdf="' + reverse("panel:factura_pdf", args=["lote1", "2026-07-01_P009.pdf"]) + '"' in html
    assert 'id="visor"' in html and "panel/panel.js" in html


def test_el_pdf_se_puede_ensenar_dentro_de_nuestra_pagina(alberto, lote_de_prueba, tmp_path):
    import pymupdf

    ruta = tmp_path / "factura.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "FACTURA")
        pdf.save(ruta)
    doc = lote_de_prueba["documentos"]["2026-07-01_P009.pdf"]
    doc.ruta = str(ruta)
    doc.save(update_fields=["ruta"])
    r = alberto.get(reverse("panel:factura_pdf", args=["lote1", "2026-07-01_P009.pdf"]))
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r["X-Frame-Options"] == "SAMEORIGIN"  # el visor lo carga en un marco de la misma web


def test_filtrar_por_proveedor_e_importe(lote_de_prueba):
    from decimal import Decimal

    from web.panel.models import Pedido, Proveedor

    p = Proveedor.objects.create(codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331", iban="ES2100491500051234567890")
    Pedido.objects.create(numero="PO-2026-0001", proveedor=p, importe=Decimal("2490"))
    todas = consultas.decisiones_de(lote_de_prueba["ejecucion"])
    assert consultas.proveedores_para_filtro() == [("P001", "Suministros Levante S.L.")]
    assert consultas.filtrar_decisiones(todas, proveedor="P001").count() == 4  # las cuatro leídas llevan su NIF; el escaneado no
    assert consultas.filtrar_decisiones(todas, proveedor="P999").count() == 0
    assert {d.documento.file_id for d in consultas.filtrar_decisiones(todas, desde=Decimal("2000"), hasta=Decimal("3000"))} == {"2026-01-08_P001.pdf"}
    assert consultas.filtrar_decisiones(todas, hasta=Decimal("400")).count() == 1  # FA-1016, 318,40 €
    assert consultas.importe_o_nada("1.200,50") == Decimal("1200.50") and consultas.importe_o_nada(" ") is None and consultas.importe_o_nada("abc") is None


def test_los_hosts_permitidos_se_leen_del_entorno(monkeypatch):
    """Por defecto los dos locales; con DJANGO_ALLOWED_HOSTS, lo que diga (túnel, dominio de la demo...)."""
    import runpy
    from pathlib import Path

    import web

    settings_py = str(Path(web.__file__).parent / "settings.py")
    monkeypatch.delenv("DJANGO_ALLOWED_HOSTS", raising=False)
    assert runpy.run_path(settings_py)["ALLOWED_HOSTS"] == ["127.0.0.1", "localhost"]
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1, pagos.ejemplo.com,")
    assert runpy.run_path(settings_py)["ALLOWED_HOSTS"] == ["127.0.0.1", "pagos.ejemplo.com"]
