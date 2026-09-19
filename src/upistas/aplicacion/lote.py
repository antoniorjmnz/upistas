from upistas.aplicacion.mapeo import a_outcome
from upistas.dominio.duplicados import resolver_duplicados
from upistas.dominio.modelos import Comprobacion, Decision, Resultado


def consolidar_lote(outcomes: list[dict]) -> list[dict]:
    decisiones = [Decision(
        file_id=o["file_id"],
        resultado=Resultado(o["result"]),
        motivo=o["motivo"],
        norma=o["norma"],
        pedido=o.get("pedido"),
        comprobaciones=tuple(Comprobacion(r["id"], r["ok"], r.get("detalle") or "") for r in o.get("reglas", [])),
    ) for o in outcomes]
    return [a_outcome(d) for d in resolver_duplicados(decisiones)]
