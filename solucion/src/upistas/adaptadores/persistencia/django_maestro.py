"""FuenteMaestro sobre nuestra base de datos: los proveedores y pedidos que Alberto mantiene en la web.

Es el relevo del Excel (`fuentes/excel.py`). Lo que antes estaba repartido en varias hojas está aquí en
dos tablas: el NIF de un pedido ya no se repite, se hereda del proveedor, y la hoja `pendiente_revisar`
es la casilla `revisar` de cada pedido. `importar` trae aquí lo que digan otras fuentes (el Excel, los
CSV de altas del lote 2) sin pisar lo que Alberto haya hecho en la web.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property

from upistas.dominio.importes import normaliza_iban
from upistas.dominio.modelos import Pedido, Proveedor
from upistas.puertos import FuenteMaestro

CENTIMOS = Decimal("0.01")


@dataclass(frozen=True)
class ResumenImportacion:
    proveedores_nuevos: int = 0
    pedidos_nuevos: int = 0
    cambiados: int = 0
    sin_proveedor: tuple[str, ...] = ()  # pedidos cuyo proveedor no está en ninguna fuente: no se cargan
    avisos: tuple[str, ...] = ()

    def __str__(self) -> str:
        return ", ".join((
            plural(self.proveedores_nuevos, "proveedor nuevo", "proveedores nuevos"),
            plural(self.pedidos_nuevos, "pedido nuevo", "pedidos nuevos"),
            plural(self.cambiados, "cambiado", "cambiados"),
        ))


def plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


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

    # --- carga desde otras fuentes ----------------------------------------------------------

    def importar(self, *fuentes: FuenteMaestro) -> ResumenImportacion:
        """Vuelca en nuestras tablas lo que digan las fuentes (el Excel, los CSV de altas). Se puede repetir.

        Lo que ya está se actualiza solo si cambia, y lo que Alberto haya hecho en la web no se pisa: la
        marca de revisar se toma de la fuente (la hoja `pendiente_revisar`) solo al crear el pedido; después
        la marca, la nota y el campo activo son suyos y no se tocan. Si dos fuentes traen el mismo código,
        manda la última.
        """
        from django.db import transaction

        from web.panel.models import Pedido as FilaPedido
        from web.panel.models import Proveedor as FilaProveedor

        avisos: list[str] = []
        proveedores: dict[str, Proveedor] = {}
        pedidos: dict[str, Pedido] = {}
        marcados: set[str] = set()
        for fuente in fuentes:
            for p in fuente.proveedores():
                if p.id in proveedores and proveedores[p.id] != p:
                    avisos.append(f"Proveedor {p.id} viene en más de una fuente con datos distintos; se toma el último")
                proveedores[p.id] = p
            for p in fuente.pedidos():
                if p.id in pedidos and pedidos[p.id] != p:
                    avisos.append(f"Pedido {p.id} viene en más de una fuente con datos distintos; se toma el último")
                pedidos[p.id] = p
            marcados |= fuente.marcados_para_revisar()

        nuevos_prov = nuevos_ped = cambiados = 0
        sin_proveedor: list[str] = []
        with transaction.atomic():
            filas_prov = {f.codigo: f for f in FilaProveedor.objects.all()}
            for p in proveedores.values():
                datos = {"nombre": p.nombre, "nif": p.nif.replace(" ", "").upper(), "iban": normaliza_iban(p.iban) or "",
                         "ciudad": p.ciudad, "condiciones_dias": p.condiciones_dias}
                estado = _guardar(filas_prov.get(p.id), FilaProveedor, {"codigo": p.id}, datos)
                nuevos_prov += estado == "nuevo"
                cambiados += estado == "cambiado"

            filas_prov = {f.codigo: f for f in FilaProveedor.objects.all()}
            filas_ped = {f.numero: f for f in FilaPedido.objects.select_related("proveedor")}
            for p in pedidos.values():
                proveedor = filas_prov.get(p.proveedor_id)
                if proveedor is None:
                    sin_proveedor.append(p.id)
                    continue
                fila = filas_ped.get(p.id)
                datos = {"proveedor": proveedor, "importe": p.importe.quantize(CENTIMOS), "fecha": p.fecha}
                if fila is None:
                    datos["revisar"] = p.id in marcados
                estado = _guardar(fila, FilaPedido, {"numero": p.id}, datos)
                nuevos_ped += estado == "nuevo"
                cambiados += estado == "cambiado"

        return ResumenImportacion(nuevos_prov, nuevos_ped, cambiados, tuple(sin_proveedor), tuple(avisos))


def _guardar(fila, modelo, clave: dict, datos: dict) -> str:
    """Crea la fila si no existe o cambia solo los campos que difieren. Devuelve nuevo, cambiado o igual."""
    if fila is None:
        modelo.objects.create(**clave, **datos)
        return "nuevo"
    cambios = {campo: valor for campo, valor in datos.items() if getattr(fila, campo) != valor}
    if not cambios:
        return "igual"
    for campo, valor in cambios.items():
        setattr(fila, campo, valor)
    fila.save(update_fields=[*cambios, "actualizado"])
    return "cambiado"
