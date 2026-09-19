"""FuenteMaestro sobre nuestra base de datos: los proveedores y pedidos que Alberto mantiene en la web.

Es el relevo del Excel (`fuentes/excel.py`). Lo que antes estaba repartido en varias hojas está aquí en
dos tablas: el NIF de un pedido ya no se repite, se hereda del proveedor, y la hoja `pendiente_revisar`
es la casilla `revisar` de cada pedido.
"""
from __future__ import annotations

import hashlib
from functools import cached_property

from upistas.dominio.modelos import Pedido, Proveedor


class MaestroDjango:
    """Los modelos se importan dentro de cada método: Django tiene que estar configurado antes."""

    @staticmethod
    def hay_datos() -> bool:
        """¿Hay proveedores dados de alta en la web? Es lo que decide si el maestro vive aquí."""
        from web.panel.models import Proveedor as Fila

        return Fila.objects.exists()

    # --- puerto FuenteMaestro --------------------------------------------------------------

    def proveedores(self) -> list[Proveedor]:
        from web.panel.models import Proveedor as Fila

        return [
            Proveedor(id=f.codigo, nombre=f.nombre, nif=f.nif, iban=f.iban, ciudad=f.ciudad,
                      condiciones_dias=f.condiciones_dias)
            for f in Fila.objects.order_by("codigo")
        ]

    def pedidos(self) -> list[Pedido]:
        from web.panel.models import Pedido as Fila

        return [
            Pedido(id=f.numero, proveedor_id=f.proveedor.codigo, nif=f.proveedor.nif,
                   importe=f.importe, estado="", fecha=f.fecha)
            for f in Fila.objects.select_related("proveedor").order_by("numero")
        ]

    def marcados_para_revisar(self) -> frozenset[str]:
        """Los pedidos cuyas facturas Alberto quiere mirar él."""
        from web.panel.models import Pedido as Fila

        return frozenset(Fila.objects.filter(revisar=True).values_list("numero", flat=True))

    @cached_property
    def version(self) -> str:
        """Huella del contenido de las dos tablas: cambia en cuanto Alberto corrige un dato.

        Se calcula una vez por instancia, así que una pasada entera decide con la foto del maestro que
        había al empezar. La nota de un pedido no entra: es para Alberto, no decide nada.
        """
        from web.panel.models import Pedido, Proveedor

        huella = hashlib.sha256()
        for f in Proveedor.objects.order_by("codigo").values_list(
            "codigo", "nombre", "nif", "iban", "ciudad", "condiciones_dias", "activo"
        ):
            huella.update("|".join(str(v) for v in f).encode() + b"\n")
        for f in Pedido.objects.order_by("numero").values_list(
            "numero", "proveedor__codigo", "importe", "fecha", "revisar"
        ):
            huella.update("|".join(str(v) for v in f).encode() + b"\n")
        return huella.hexdigest()[:12]
