"""Trae el maestro de La Caja (el Excel de Alberto y los CSV de altas) a nuestras tablas. Se puede repetir sin miedo."""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from upistas.adaptadores.fuentes.csv_altas import AltasCSV
from upistas.adaptadores.fuentes.excel import MaestroExcel
from upistas.adaptadores.persistencia.django_maestro import MaestroDjango, plural
from upistas.config import settings

NOMBRE = "FINAL_v7_DEFINITIVO_ahorasi.xlsx"


class Command(BaseCommand):
    help = "Carga en el maestro de la web los proveedores y pedidos del Excel de La Caja y de los CSV de altas."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--excel", default=None, help=f"Ruta del Excel (por defecto, {NOMBRE} en CAJA_DIR)")
        parser.add_argument("--proveedores-csv", action="append", default=[], metavar="FICHERO",
                            help="CSV de proveedores nuevos (ID, Razon Social, NIF, IBAN, Ciudad, Condiciones); se puede repetir")
        parser.add_argument("--pedidos-csv", action="append", default=[], metavar="FICHERO",
                            help="CSV de pedidos nuevos (pedido, proveedor_id, nif, importe_total, estado, fecha_pedido); se puede repetir")

    def handle(self, *args, **opciones) -> None:
        proveedores_csv = tuple(Path(r) for r in opciones["proveedores_csv"])
        pedidos_csv = tuple(Path(r) for r in opciones["pedidos_csv"])
        for ruta in (*proveedores_csv, *pedidos_csv):
            if not ruta.is_file():
                raise CommandError(f"No encuentro el CSV: {ruta}")

        fuentes = []
        ruta_excel = Path(opciones["excel"]) if opciones["excel"] else settings.caja_dir / NOMBRE
        if ruta_excel.is_file():
            fuentes.append(MaestroExcel(ruta_excel))
        elif opciones["excel"] or not (proveedores_csv or pedidos_csv):
            raise CommandError(f"No encuentro el Excel: {ruta_excel}")
        if proveedores_csv or pedidos_csv:
            fuentes.append(AltasCSV(proveedores_csv, pedidos_csv))

        resumen = MaestroDjango().importar(*fuentes)

        for fuente in fuentes:
            leido = f"{plural(len(fuente.proveedores()), 'proveedor', 'proveedores')}, {plural(len(fuente.pedidos()), 'pedido', 'pedidos')}"
            if isinstance(fuente, MaestroExcel):
                marcados = plural(len(fuente.marcados_para_revisar()), "marcado para revisar", "marcados para revisar")
                self.stdout.write(f"Excel {fuente.ruta.name}: {leido}, {marcados}")
            else:
                self.stdout.write(f"CSV: {leido}")
        self.stdout.write(str(resumen))
        if resumen.sin_proveedor:
            self.stdout.write(f"Sin proveedor conocido, no se cargan: {len(resumen.sin_proveedor)} ({', '.join(resumen.sin_proveedor[:5])})")
        for aviso in (*(a for f in fuentes for a in f.avisos), *resumen.avisos):
            self.stdout.write(f"Aviso: {aviso}")
