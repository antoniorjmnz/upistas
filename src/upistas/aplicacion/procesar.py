"""Caso de uso principal: un documento → una decisión."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.modelos import Decision, Referencias, Resultado
from upistas.dominio.norma import Norma
from upistas.puertos import LecturaFallida, LectorDocumento

from upistas.aplicacion.mapeo import a_factura


def leer_documento(ruta: Path, lectores: Sequence[LectorDocumento]) -> FacturaExtraida | None:
    """Prueba los lectores en orden (del más barato al más caro) hasta que uno lo consiga."""
    for lector in lectores:
        if not lector.acepta(ruta):
            continue
        try:
            return lector.leer(ruta)
        except LecturaFallida:
            continue
    return None


def decidir(file_id: str, extraida: FacturaExtraida | None, refs: Referencias, norma: Norma) -> Decision:
    if extraida is None:
        return Decision(
            file_id=file_id,
            resultado=Resultado.ESCALAR,
            motivo="Ningún lector pudo extraer la factura",
            norma=norma.version,
        )
    if extraida.errores:
        return Decision(
            file_id=file_id,
            resultado=Resultado.ESCALAR,
            motivo="; ".join(extraida.errores),
            norma=norma.version,
            pedido=extraida.campos.pedido.valor,
        )
    return norma.evaluar(a_factura(extraida), refs)
