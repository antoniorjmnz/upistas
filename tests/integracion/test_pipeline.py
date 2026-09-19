"""El pipeline de punta a punta sobre documentos de prueba, con DBOS y la base de datos de tests."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from dbos import DBOS

from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.modelos import Asiento
from upistas.infra import django_setup, pipeline
from upistas.puertos import DescargaERP, EstadisticasDescarga

pytestmark = pytest.mark.django_db(transaction=True)


class ClienteFalso:
    def __init__(self, asientos):
        self.asientos = asientos

    def descargar(self):
        return DescargaERP(asientos=self.asientos, lote2_cargado=False, estadisticas=EstadisticasDescarga(peticiones=1))


@pytest.fixture(scope="module")
def dbos_lanzado():
    django_setup.configurar(migrar=False)  # pytest-django ya crea la base de datos de tests
    pipeline.iniciar()
    yield
    DBOS.destroy()


@pytest.fixture
def carpeta(tmp_path):
    def pdf(nombre, texto=None):
        doc = pymupdf.open()
        pagina = doc.new_page()
        if texto:
            pagina.insert_text((72, 72), texto)
        doc.save(tmp_path / nombre)
        doc.close()

    pdf("con_texto.pdf", "FACTURA 2026/0001 Pedido: PO-2026-0001 NIF: B46102331 TOTAL: 121,00")
    pdf("en_blanco.pdf")
    (tmp_path / "no_es_pdf.txt").write_text("hola", encoding="utf-8")
    return tmp_path


def test_lee_decide_y_guarda_cada_documento(dbos_lanzado, carpeta, monkeypatch):
    from upistas.infra import contenedor

    monkeypatch.setattr(contenedor, "cliente_erp", lambda: ClienteFalso((
        Asiento("AS-00001", "PO-2026-0001", "P001", "B46102331", Decimal("121.00"), date(2026, 1, 8), "PENDIENTE"),
    )))
    rutas = sorted(p for p in carpeta.iterdir())
    inf = pipeline.procesar_lote("test", rutas, "v3", sincronizar=True)

    por = {d.file_id: d for d in inf.decisiones}
    assert set(por) == {"con_texto.pdf", "en_blanco.pdf", "no_es_pdf.txt"}
    # El lector de texto es todavía un hueco (#23): con texto acaba en ESCALAR explicando por qué.
    assert por["con_texto.pdf"].resultado == "ESCALAR" and "pendiente" in por["con_texto.pdf"].motivo
    assert por["en_blanco.pdf"].resultado == "ESCALAR" and "blanco" in por["en_blanco.pdf"].motivo
    assert inf.ejecucion.estado == "terminada" and inf.ejecucion.version_erp
    assert inf.ejecucion.resumen["documentos"] == 3 and inf.ejecucion.resumen["ESCALAR"] == 3
    assert inf.sincronizacion is not None and inf.sincronizacion.ok

    # Todo queda en la base de datos: documentos, lecturas (también las fallidas) y decisiones.
    from web.panel.models import Decision, Documento, Lectura

    assert Documento.objects.filter(lote="test").count() == 3
    assert Lectura.objects.filter(lote="test").count() == 3 and not Lectura.objects.filter(ok=True).exists()
    assert Decision.objects.filter(ejecucion_id=inf.ejecucion.id).count() == 3


def test_repetir_el_lote_no_relee_y_compara_con_la_pasada_anterior(dbos_lanzado, carpeta, monkeypatch):
    from upistas.infra import contenedor

    asiento = Asiento("AS-00001", "PO-2026-0001", "P001", "B46102331", Decimal("121.00"), date(2026, 1, 8), "PENDIENTE")
    monkeypatch.setattr(contenedor, "cliente_erp", lambda: ClienteFalso((asiento,)))
    rutas = sorted(p for p in carpeta.iterdir())
    primera = pipeline.procesar_lote("test", rutas, "v3")
    segunda = pipeline.procesar_lote("test", rutas, "v3", sincronizar=False)

    assert segunda.anterior is not None and segunda.anterior.id == primera.ejecucion.id
    assert segunda.cambios == []  # mismos datos, misma norma: nada cambia
    assert segunda.ejecucion.version_datos == primera.ejecucion.version_datos

    # Cambia el ERP (el pedido pasa a pagado): nueva versión de datos y la pasada lo registra.
    monkeypatch.setattr(contenedor, "cliente_erp", lambda: ClienteFalso((replace(asiento, estado="PAGADA"),)))
    tercera = pipeline.procesar_lote("test", rutas, "v3")
    assert tercera.ejecucion.version_erp != segunda.ejecucion.version_erp
    assert tercera.sincronizacion.modificados == 1
