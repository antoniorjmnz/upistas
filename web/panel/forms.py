"""Los formularios del maestro: lo que Alberto escribe al dar de alta un proveedor o un pedido.

Se pintan a mano en las plantillas (`.formulario`), así que aquí solo están las etiquetas en sus
palabras, los tipos de casilla y las comprobaciones. El formato del NIF y del número de pedido es el
mismo que se le exige al Excel, para que las dos fuentes digan lo mismo.
"""
from __future__ import annotations

from decimal import Decimal

from django import forms

from upistas.adaptadores.fuentes.excel import PATRON_NIF, PATRON_PEDIDO
from upistas.dominio.importes import normaliza_iban
from web.panel.models import Pedido, Proveedor


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ["nombre", "nif", "iban", "codigo", "ciudad", "condiciones_dias"]
        labels = {
            "nombre": "Nombre",
            "nif": "NIF",
            "iban": "Cuenta bancaria (IBAN)",
            "codigo": "Código en el ERP",
            "ciudad": "Ciudad",
            "condiciones_dias": "Días de pago",
        }
        help_texts = {
            "nif": "Una letra, siete números y una letra o número. Por ejemplo, B46102331.",
            "iban": "La cuenta donde cobra. Se compara con la que traiga cada factura suya.",
            "codigo": "Así le llama el ERP en sus asientos. Por ejemplo, P001.",
            "ciudad": "Si no la sabe, déjelo en blanco.",
            "condiciones_dias": "Cuántos días hay para pagarle. Por ejemplo, 30 o 60. Puede dejarlo en blanco.",
        }
        error_messages = {
            "codigo": {"unique": "Ya hay otro proveedor con ese código."},
            "nif": {"unique": "Ya hay otro proveedor con ese NIF."},
        }
        widgets = {
            "nombre": forms.TextInput(attrs={"autocomplete": "off"}),
            "nif": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "B46102331"}),
            "iban": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "ES21 0049 1500 0512 3456 7890"}),
            "codigo": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "P001"}),
            "ciudad": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def clean_nif(self) -> str:
        nif = self.cleaned_data["nif"].replace(" ", "").upper()
        if not PATRON_NIF.match(nif):
            raise forms.ValidationError("El NIF lleva una letra, siete números y una letra o número, como B46102331.")
        return nif

    def clean_iban(self) -> str:
        iban = normaliza_iban(self.cleaned_data["iban"]) or ""
        if iban.startswith("ES") and len(iban) != 24:
            raise forms.ValidationError("Una cuenta española tiene 24 caracteres: ES y 22 números.")
        return iban

    def clean_codigo(self) -> str:
        return self.cleaned_data["codigo"].strip().upper()


class PedidoForm(forms.ModelForm):
    proveedor = forms.ModelChoiceField(
        queryset=Proveedor.objects.all(), label="Proveedor", empty_label="Elija un proveedor",
    )
    fecha = forms.DateField(
        required=False, label="Fecha",
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="La del pedido, no la de la factura. Puede dejarlo en blanco.",
    )

    class Meta:
        model = Pedido
        fields = ["numero", "proveedor", "importe", "fecha", "revisar", "nota"]
        labels = {
            "numero": "Número de pedido",
            "proveedor": "Proveedor",
            "importe": "Importe",
            "revisar": "Alberto quiere mirar las facturas de este pedido",
            "nota": "Nota",
        }
        help_texts = {
            "numero": "Se escribe PO, el año y cuatro números. Por ejemplo, PO-2026-0001.",
            "importe": "Lo que se pidió, con IVA. Una factura de este pedido tiene que coincidir.",
            "nota": "Para usted. No cambia ninguna decisión.",
        }
        error_messages = {"numero": {"unique": "Ya hay otro pedido con ese número."}}
        widgets = {
            "numero": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "PO-2026-0001"}),
            "importe": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "nota": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_numero(self) -> str:
        numero = self.cleaned_data["numero"].strip().upper()
        if not PATRON_PEDIDO.match(numero):
            raise forms.ValidationError("El número de pedido se escribe PO, el año y cuatro cifras, como PO-2026-0001.")
        return numero

    def clean_importe(self) -> Decimal:
        importe = self.cleaned_data["importe"]
        if importe <= 0:
            raise forms.ValidationError("El importe tiene que ser mayor que cero.")
        return importe
