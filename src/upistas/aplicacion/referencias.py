"""Montar todo lo que las reglas pueden consultar, una vez por lote."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from upistas.dominio.modelos import Asiento, FacturaResumen, Referencias
from upistas.puertos import FuenteERP, FuenteMaestro, RegistroLectura

from upistas.aplicacion.mapeo import a_factura


def vigente_por_pedido(asientos: Sequence[Asiento]) -> dict[str, Asiento]:
    """Un asiento por pedido: si el ERP registra varios (export incremental), manda el más reciente."""
    vigente: dict[str, Asiento] = {}
    for a in asientos:
        previo = vigente.get(a.pedido)
        if previo is None or (a.fecha or date.min) > (previo.fecha or date.min):
            vigente[a.pedido] = a
    return vigente


def construir_referencias(
    maestro: FuenteMaestro,
    erp: FuenteERP,
    lecturas_del_lote: Sequence[RegistroLectura],
    hoy: date,
    version_erp: str,
    pedidos_ya_decididos: frozenset[str] = frozenset(),
    hashes_ya_aprobados: frozenset[str] = frozenset(),
) -> Referencias:
    por_pedido: dict[str, list[FacturaResumen]] = defaultdict(list)
    for r in lecturas_del_lote:
        if r.extraida is None:
            continue
        f = a_factura(r.extraida)
        if f.pedido:
            por_pedido[f.pedido].append(FacturaResumen(f.file_id, f.numero, f.fecha, f.total, f.nif))
    asientos = vigente_por_pedido(erp.asientos())
    proveedores = maestro.proveedores()
    return Referencias(
        proveedores={p.nif: p for p in proveedores if p.nif},
        proveedores_por_id={p.id: p for p in proveedores},
        hashes_ya_aprobados=hashes_ya_aprobados,
        pedidos={p.id: p for p in maestro.pedidos()},
        asientos=asientos,
        hoy=hoy,
        pedidos_ya_decididos=pedidos_ya_decididos,
        marcados_por_alberto=maestro.marcados_para_revisar(),
        facturas_del_lote={k: tuple(v) for k, v in por_pedido.items()},
        version_datos=f"{version_erp}+{maestro.version}",
    )
