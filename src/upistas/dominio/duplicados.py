from collections import Counter
from dataclasses import replace

from upistas.dominio.modelos import Comprobacion, Decision, Resultado


def resolver_duplicados(decisiones: list[Decision]) -> list[Decision]:
    recuento = Counter(d.pedido for d in decisiones if d.pedido)
    resultado = []
    for decision in decisiones:
        if decision.pedido and recuento[decision.pedido] > 1:
            detalle = f"Pedido duplicado en el lote: {decision.pedido}"
            decision = replace(
                decision,
                resultado=Resultado.ESCALAR if decision.resultado == Resultado.PAGAR else decision.resultado,
                motivo=f"{decision.motivo}; {detalle}",
                comprobaciones=decision.comprobaciones + (Comprobacion("R5_duplicado", False, detalle),),
            )
        resultado.append(decision)
    return resultado
