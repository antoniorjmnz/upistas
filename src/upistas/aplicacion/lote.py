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
        alertas=tuple(o.get("alertas") or []),
    ) for o in outcomes]
    return [{**original, **a_outcome(d, version_datos=original.get("version_datos") or "", metodo=original.get("metodo"))}
            for original, d in zip(outcomes, resolver_duplicados(decisiones))]
