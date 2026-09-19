"""Decidir un lote entero y comparar dos pasadas."""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from upistas.dominio.modelos import Referencias
from upistas.dominio.norma import Norma
from upistas.puertos import DecisionGuardada, RegistroLectura

from upistas.aplicacion import procesar
from upistas.aplicacion.mapeo import a_outcome


def decidir_lote(lecturas: Sequence[RegistroLectura], refs: Referencias, norma: Norma) -> list[DecisionGuardada]:
    """Rápido y determinista: las reglas no hablan con nadie. Se puede repetir cuantas veces haga falta."""
    salida = []
    for r in sorted(lecturas, key=lambda x: x.file_id):
        lectura = procesar.Lectura(documento=r.documento(), extraida=r.extraida, intentos=r.intentos)
        d = procesar.decidir(r.file_id, lectura, refs, norma)
        outcome = a_outcome(d, refs.version_datos, r.metodo)
        notas = tuple({"texto": n.texto, "categorias": [c.value for c in n.categorias]} for n in (r.extraida.notas or [])) if r.extraida else ()
        salida.append(
            DecisionGuardada(
                file_id=r.file_id, resultado=d.resultado.value, motivo=d.motivo, pedido=d.pedido,
                metodo=r.metodo, outcome=outcome, notas=notas, alertas=tuple(d.alertas),
            )
        )
    return salida


def resumen(decisiones: Sequence[DecisionGuardada], lecturas: Sequence[RegistroLectura]) -> dict:
    resultados = Counter(d.resultado for d in decisiones)
    metodos = Counter(r.metodo for r in lecturas)
    return {
        "documentos": len(lecturas),
        "PAGAR": resultados.get("PAGAR", 0),
        "NO_PAGAR": resultados.get("NO_PAGAR", 0),
        "ESCALAR": resultados.get("ESCALAR", 0),
        "leidos": sum(1 for r in lecturas if r.leida),
        "por_metodo": dict(metodos),
        "con_alertas": sum(1 for d in decisiones if d.alertas),
        "con_notas": sum(1 for d in decisiones if d.notas),
        "tokens_in": sum(r.tokens_in for r in lecturas),
        "tokens_out": sum(r.tokens_out for r in lecturas),
        "coste_eur": round(sum(r.coste_eur for r in lecturas), 4),
        "segundos_lectura_acumulados": round(sum(r.segundos for r in lecturas), 2),
    }


@dataclass(frozen=True)
class Cambio:
    file_id: str
    antes: str
    despues: str
    motivo: str


def comparar(antes: Sequence[DecisionGuardada], despues: Sequence[DecisionGuardada]) -> list[Cambio]:
    """Qué facturas cambian de resultado entre dos pasadas (p. ej. tras el lote 2 o el dato del domingo)."""
    previas = {d.file_id: d for d in antes}
    cambios = []
    for d in sorted(despues, key=lambda x: x.file_id):
        p = previas.get(d.file_id)
        if p is not None and p.resultado != d.resultado:
            cambios.append(Cambio(d.file_id, p.resultado, d.resultado, d.motivo))
    return cambios
