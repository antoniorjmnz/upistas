"""Montar todo lo que las reglas pueden consultar, una vez por lote."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from upistas.dominio.modelos import FacturaResumen, Referencias
from upistas.puertos import FuenteERP, FuenteMaestro, RegistroLectura

from upistas.aplicacion.mapeo import a_factura


def construir_referencias(
    maestro: FuenteMaestro,
    erp: FuenteERP,
    lecturas_del_lote: Sequence[RegistroLectura],
    hoy: date,
    version_erp: str,
    pedidos_ya_decididos: frozenset[str] = frozenset(),
) -> Referencias:
    por_pedido: dict[str, list[FacturaResumen]] = defaultdict(list)
    for r in lecturas_del_lote:
        if r.extraida is None:
            continue
        f = a_factura(r.extraida)
        if f.pedido:
            por_pedido[f.pedido].append(FacturaResumen(f.file_id, f.numero, f.fecha, f.total, f.nif))
    return Referencias(
        proveedores={p.nif: p for p in maestro.proveedores()},
        pedidos={p.id: p for p in maestro.pedidos()},
        asientos={a.pedido: a for a in erp.asientos()},
        hoy=hoy,
        pedidos_ya_decididos=pedidos_ya_decididos,
        marcados_por_alberto=maestro.marcados_para_revisar(),
        facturas_del_lote={k: tuple(v) for k, v in por_pedido.items()},
        version_datos=f"{version_erp}+{maestro.version}",
    )
