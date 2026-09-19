"""Decidir un lote entero y comparar dos pasadas."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from upistas.dominio.duplicados import resolver_duplicados
from upistas.dominio.modelos import Comprobacion, Decision, Factura, Referencias, Resultado
from upistas.dominio.norma import Norma
from upistas.puertos import DecisionGuardada, RegistroLectura

from upistas.aplicacion import procesar
from upistas.aplicacion.mapeo import a_factura, a_outcome


def consolidar_lote(outcomes: list[dict], facturas: Mapping[str, Factura] | None = None,
                    hashes_aprobados: frozenset[str] = frozenset()) -> list[dict]:
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
            for original, d in zip(outcomes, resolver_duplicados(decisiones, facturas, hashes_aprobados))]


def decidir_lote(lecturas: Sequence[RegistroLectura], refs: Referencias, norma: Norma) -> list[DecisionGuardada]:
    """Rápido y determinista: las reglas no hablan con nadie. Se puede repetir cuantas veces haga falta."""
    salida = []
    for r in sorted(lecturas, key=lambda x: x.file_id):
        lectura = procesar.Lectura(documento=r.documento(), extraida=r.extraida, intentos=r.intentos)
        d = procesar.decidir(r.file_id, lectura, refs, norma)
        if r.sha256:
            d = replace(d, comprobaciones=d.comprobaciones + (Comprobacion("D0_sha256", True, r.sha256),))
        outcome = a_outcome(d, refs.version_datos, r.metodo)
        notas = tuple({"texto": n.texto, "categorias": [c.value for c in n.categorias]} for n in (r.extraida.notas or [])) if r.extraida else ()
        salida.append(
            DecisionGuardada(
                file_id=r.file_id, resultado=d.resultado.value, motivo=d.motivo, pedido=d.pedido,
                metodo=r.metodo, outcome=outcome, notas=notas, alertas=tuple(d.alertas),
            )
        )
    facturas = {r.file_id: replace(a_factura(r.extraida), sha256=r.sha256) if r.extraida
                else Factura(r.file_id, sha256=r.sha256) for r in lecturas}
    consolidados = consolidar_lote([d.outcome for d in salida], facturas, refs.hashes_ya_aprobados)
    return [replace(d, resultado=o["result"], motivo=o["motivo"], outcome=o) for d, o in zip(salida, consolidados)]


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
