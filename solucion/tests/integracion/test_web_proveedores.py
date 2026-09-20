"""La pantalla de Proveedores: la lista, el detalle de cada uno y los formularios del maestro."""
from decimal import Decimal

import pytest
from django.urls import reverse

from web.panel.models import Pedido, Proveedor

pytestmark = pytest.mark.django_db


@pytest.fixture
def levante():
    proveedor = Proveedor.objects.create(
        codigo="P001", nombre="Suministros Levante S.L.", nif="B46102331",
        iban="ES2100491500051234567890", ciudad="Valencia", condiciones_dias=60,
    )
    Pedido.objects.create(numero="PO-2026-0001", proveedor=proveedor, importe=Decimal("2490.00"))
    Pedido.objects.create(numero="PO-2026-0007", proveedor=proveedor, importe=Decimal("880.55"), revisar=True)
    Proveedor.objects.create(codigo="P003", nombre="Ofimática Cieza S.L.", nif="B30455812",
                             iban="ES6001825322180201588391")
    return proveedor


def lista(alberto, **filtros) -> str:
    return alberto.get(reverse("panel:proveedores"), filtros).content.decode()


def test_la_lista_dice_para_que_sirve_y_ensena_lo_que_hace_falta(alberto, levante):
    html = lista(alberto)
    assert "Los proveedores a los que usted paga" in html and "sin tocar el Excel" in html
    assert "Nuevo proveedor" in html and reverse("panel:proveedor_nuevo") in html
    assert "Suministros Levante S.L." in html and ">P001<" in html
    assert "B46102331" in html and "ES2100491500051234567890" in html
    assert ">SL</span>" in html  # el avatar con sus iniciales
    assert "1 para mirar" in html and "60 días" in html
    assert reverse("panel:proveedor", args=[levante.id]) in html


def test_sin_proveedores_explica_como_empezar(alberto):
    html = lista(alberto)
    assert "Todavía no hay ningún proveedor" in html and 'class="vacio"' in html
    assert reverse("panel:proveedor_nuevo") in html


def test_se_busca_por_nombre_nif_o_codigo(alberto, levante):
    assert "Ofimática Cieza" not in lista(alberto, q="levante")
    assert "Suministros Levante" in lista(alberto, q="B46102331")
    assert "Suministros Levante" in lista(alberto, q="P001")
    vacia = lista(alberto, q="ferretería")
    assert "Ningún proveedor se llama así" in vacia and "2 proveedores" in vacia


def test_el_detalle_ensena_sus_datos_sus_pedidos_y_sus_facturas(alberto, levante, lote_de_prueba):
    html = alberto.get(reverse("panel:proveedor", args=[levante.id])).content.decode()
    assert "Volver a proveedores" in html
    assert "P001 · B46102331" in html and "ES2100491500051234567890" in html
    assert "Valencia" in html and "60 días" in html and "De alta" in html
    assert reverse("panel:proveedor_editar", args=[levante.id]) in html
    assert "Nuevo pedido" not in html  # los pedidos nacen en el ERP y en el maestro, no aquí

    assert "PO-2026-0001" in html and "2.490,00 €" in html
    assert "Revisar" in html and "1 para mirar" in html
    pedido = Pedido.objects.get(numero="PO-2026-0007")
    assert reverse("panel:pedido_editar", args=[pedido.id]) in html

    # La factura del lote que va contra PO-2026-0001, con su resultado y su motivo.
    assert reverse("panel:factura", args=["lote1", "2026-01-08_P001.pdf"]) in html
    assert '<span class="pildora bien">Pagar</span>' in html and "Cumple la norma" in html
    assert "FA-1016" not in html  # la de otro pedido, no


def test_el_detalle_sin_pedidos_ni_repasos_no_parece_un_error(alberto):
    solo = Proveedor.objects.create(codigo="P009", nombre="Papelería Ruzafa S.C.", nif="J40112358",
                                    iban="ES5531590012348765123407")
    html = alberto.get(reverse("panel:proveedor", args=[solo.id])).content.decode()
    assert "Todavía no le ha apuntado ningún pedido" in html
    assert "Todavía no se ha repasado ningún lote" in html


def test_dar_de_alta_un_proveedor(alberto, levante):
    formulario = alberto.get(reverse("panel:proveedor_nuevo")).content.decode()
    assert "Cuenta bancaria (IBAN)" in formulario and "Código en el ERP" in formulario
    assert "Días de pago" in formulario and "form.as_p" not in formulario

    r = alberto.post(reverse("panel:proveedor_nuevo"), {
        "nombre": "Limpiezas Turia S.L.", "nif": "b12345674", "codigo": "p012",
        "iban": "ES91 2100 0418 4502 0005 1332", "ciudad": "Valencia", "condiciones_dias": "30",
    }, follow=True)

    nuevo = Proveedor.objects.get(codigo="P012")
    assert r.redirect_chain[-1][0] == reverse("panel:proveedor", args=[nuevo.id])
    assert "Guardado: Limpiezas Turia S.L." in r.content.decode()
    assert nuevo.nif == "B12345674" and nuevo.iban == "ES9121000418450200051332"


def test_el_alta_no_traga_un_nif_ni_una_cuenta_que_no_valen(alberto):
    r = alberto.post(reverse("panel:proveedor_nuevo"), {
        "nombre": "Proveedor Falso", "nif": "1234", "codigo": "P404", "iban": "ES0001",
    })
    html = r.content.decode()
    assert r.status_code == 200 and not Proveedor.objects.exists()
    assert "El NIF lleva una letra, siete números" in html
    assert "Una cuenta española tiene 24 caracteres" in html
    assert 'class="campo con-error"' in html


def test_el_alta_avisa_si_el_codigo_o_el_nif_ya_estan(alberto, levante):
    html = alberto.post(reverse("panel:proveedor_nuevo"), {
        "nombre": "Otro", "nif": "B46102331", "codigo": "P001", "iban": "ES2100491500051234567890",
    }).content.decode()
    assert "Ya hay otro proveedor con ese código." in html
    assert "Ya hay otro proveedor con ese NIF." in html


def test_corregir_la_cuenta_de_un_proveedor(alberto, levante):
    r = alberto.post(reverse("panel:proveedor_editar", args=[levante.id]), {
        "nombre": levante.nombre, "nif": levante.nif, "codigo": levante.codigo,
        "iban": "ES91 2100 0418 4502 0005 1332", "ciudad": "Valencia", "condiciones_dias": "60",
    }, follow=True)

    levante.refresh_from_db()
    assert levante.iban == "ES9121000418450200051332"
    assert "Guardado: Suministros Levante S.L." in r.content.decode()
    assert r.redirect_chain[-1][0] == reverse("panel:proveedor", args=[levante.id])


def test_marcar_un_pedido_para_mirarlo(alberto, levante):
    pedido = Pedido.objects.get(numero="PO-2026-0001")
    formulario = alberto.get(reverse("panel:pedido_editar", args=[pedido.id])).content.decode()
    assert "Quiero mirar las facturas de este pedido" in formulario and "2.490,00 €" in formulario
    assert "Número de pedido" not in formulario  # el número y el importe no se tocan desde aquí

    r = alberto.post(reverse("panel:pedido_editar", args=[pedido.id]), {"revisar": "on", "nota": "Llamar antes de pagar"}, follow=True)

    pedido.refresh_from_db()
    assert pedido.revisar is True and pedido.nota == "Llamar antes de pagar"
    assert pedido.importe == Decimal("2490.00")  # lo que no está en el formulario no cambia
    assert "Guardado lo que ha dicho sobre el pedido PO-2026-0001." in r.content.decode()
    assert "2 para mirar" in r.content.decode()
