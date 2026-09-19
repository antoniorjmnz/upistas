"""Trae el maestro de La Caja (el Excel de Alberto) a nuestras tablas. Se puede repetir sin miedo."""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.config import settings
from web.panel.models import Pedido, Proveedor

NOMBRE = "FINAL_v7_DEFINITIVO_ahorasi.xlsx"


class Command(BaseCommand):
    help = "Carga los proveedores y pedidos del Excel de La Caja en el maestro de la web."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--excel", default=None, help=f"Ruta del Excel (por defecto, {NOMBRE} en CAJA_DIR)")

    def handle(self, *args, **opciones) -> None:
        ruta = Path(opciones["excel"]) if opciones["excel"] else settings.caja_dir / NOMBRE
        if not ruta.is_file():
            raise CommandError(f"No encuentro el Excel: {ruta}")

        excel = MaestroExcel(ruta)
        proveedores, pedidos = excel.proveedores(), excel.pedidos()
        marcados = excel.marcados_para_revisar()

        with transaction.atomic():
            nuevos_prov = 0
            for p in proveedores:
                _, creado = Proveedor.objects.update_or_create(
                    codigo=p.id,
                    defaults={"nombre": p.nombre, "nif": p.nif, "iban": p.iban, "ciudad": p.ciudad,
                              "condiciones_dias": p.condiciones_dias},
                )
                nuevos_prov += creado

            por_codigo = {f.codigo: f for f in Proveedor.objects.all()}
            nuevos_ped, sin_proveedor = 0, []
            for p in pedidos:
                proveedor = por_codigo.get(p.proveedor_id)
                if proveedor is None:
                    sin_proveedor.append(p.id)
                    continue
                _, creado = Pedido.objects.update_or_create(
                    numero=p.id,
                    defaults={"proveedor": proveedor, "importe": p.importe, "fecha": p.fecha,
                              "revisar": p.id in marcados},
                )
                nuevos_ped += creado

        self.stdout.write(f"Proveedores: {len(proveedores)} ({nuevos_prov} nuevos)")
        self.stdout.write(f"Pedidos: {len(pedidos) - len(sin_proveedor)} ({nuevos_ped} nuevos)")
        self.stdout.write(f"Marcados para revisar: {len(marcados)}")
        if sin_proveedor:
            self.stdout.write(f"Sin proveedor conocido, no se cargan: {len(sin_proveedor)} ({', '.join(sin_proveedor[:5])})")
        for aviso in excel.avisos:
            self.stdout.write(f"Aviso del Excel: {aviso}")
