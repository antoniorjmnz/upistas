from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
from upistas.aplicacion.sincronizar_erp import sincronizar_erp
from upistas.dominio.modelos import Asiento
from upistas.puertos import DescargaERP, ErrorERP, EstadisticasDescarga

pytestmark = pytest.mark.django_db

BASE = Asiento("AS-00084", "PO-2026-0084", "P002", "A41220987", Decimal("6199.54"), date(2026, 3, 21), "PENDIENTE")
LOTE = (
    BASE,
    replace(BASE, id="AS-00474", pedido="PO-2026-0474", proveedor_id="P007", nif="J40112358", estado="PAGADA"),
    replace(BASE, id="AS-00507", pedido="PO-2026-0546", proveedor_id="P005", nif=""),
)


class Cliente:
    def __init__(self, *r):
        self.r = list(r)

    def descargar(self):
        x = self.r.pop(0)
        if isinstance(x, Exception):
            raise x
        return DescargaERP(asientos=x, lote2_cargado=False, estadisticas=EstadisticasDescarga(peticiones=30, reintentos_ora=2, segundos=3.9))


@pytest.fixture
def con_copia():
    return sincronizar_erp(Cliente(LOTE), AlmacenERPDjango())


def test_inicio_lleva_a_la_conexion(client):
    r = client.get("/")
    assert r.status_code == 302 and r.url == reverse("panel:conexion")


def test_conexion_sin_copia_lo_explica(client):
    r = client.get(reverse("panel:conexion"))
    assert r.status_code == 200
    assert "Aún no hay copia del ERP" in r.content.decode()


def test_conexion_con_copia_muestra_cifras_e_historial(client, con_copia):
    html = client.get(reverse("panel:conexion")).content.decode()
    assert con_copia.version in html
    assert "Correcta" in html and "Primera copia" in html
    assert ">1</b><span>ya pagados" in html.replace("\n", "").replace("  ", "")


def test_fallo_del_erp_se_avisa_y_se_sigue_con_la_copia(client, con_copia):
    sincronizar_erp(Cliente(ErrorERP("El ERP no responde")), AlmacenERPDjango())
    html = client.get(reverse("panel:conexion")).content.decode()
    assert "El ERP no respondió" in html and "Seguimos trabajando con la copia" in html


def test_boton_sincronizar_devuelve_el_estado_nuevo(client, con_copia, monkeypatch):
    from upistas.infra import contenedor

    cambiado = (LOTE[0], LOTE[1], replace(LOTE[2], estado="PAGADA"))
    monkeypatch.setattr(contenedor, "cliente_erp", lambda: Cliente(cambiado))
    r = client.post(reverse("panel:sincronizar"), HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert r.status_code == 200 and "<html" not in html  # solo el fragmento para htmx
    assert "1 modificados" in html
    assert reverse("panel:cambios", args=[con_copia.version, AlmacenERPDjango().ultima().version]) in html


def test_asientos_busca_por_pedido_y_filtra_por_estado(client, con_copia):
    url = reverse("panel:asientos")
    assert "PO-2026-0546" in client.get(url, {"q": "0546"}).content.decode()
    html = client.get(url, {"estado": "PAGADA"}, HTTP_HX_REQUEST="true").content.decode()
    assert "PO-2026-0474" in html and "PO-2026-0084" not in html
    assert "sin NIF" in client.get(url).content.decode()


def test_cambios_entre_versiones(client, con_copia):
    b = sincronizar_erp(Cliente((LOTE[0], replace(LOTE[1], importe=Decimal("1.00")))), AlmacenERPDjango())
    html = client.get(reverse("panel:cambios", args=[con_copia.version, b.version])).content.decode()
    assert "AS-00474" in html and "importe" in html  # modificado
    assert "AS-00507" in html  # eliminado
    compacto = "".join(html.split())
    assert "<b>2</b><span>pedidosafectados" in compacto  # PO-0474 (modificado) y PO-0546 (eliminado)
