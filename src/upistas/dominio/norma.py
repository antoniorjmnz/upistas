"""La norma de pagos como datos: qué reglas aplican y qué pasa si falla cada una."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from upistas.dominio import reglas
from upistas.dominio.divisas import TiposDeCambio
from upistas.dominio.modelos import GRAVEDAD, Comprobacion, Decision, Factura, Referencias, Resultado

# Reglas de revisión: la factura cumple los datos de la norma y aun así la mira una persona.
REVISION = frozenset({"R6_notas", "R6_contenido_oculto", "R6_revision_interna"})
MAX_CAUSAS = 3  # causas que caben en el motivo; todas las comprobaciones van en reglas[]


@dataclass(frozen=True)
class ReglaActiva:
    nombre: str
    si_falla: Resultado
    params: dict[str, Any] = field(default_factory=dict)
    prioridad: int = 0


Fallida = tuple[ReglaActiva, Comprobacion]


def _en_minuscula(frase: str) -> str:
    """«La nota pide…» → «la nota pide…»; una sigla al principio («IBAN…») se deja como está."""
    return frase[0].lower() + frase[1:] if len(frase) > 1 and frase[1].islower() else frase


def motivo_de(fallidas: list[Fallida], decisiva: Fallida) -> str:
    """El motivo empieza por la causa que fija el resultado; siguen las demás por prioridad (los avisos al
    final) y, pasadas MAX_CAUSAS, solo se cuentan. Un pago previo probado va delante de la revisión que lo
    escala, y una factura que solo escala por revisión lo dice: cumple la norma."""
    regla, _ = decisiva
    resto = sorted((par for par in fallidas if par is not decisiva), key=lambda par: -par[0].prioridad)
    causas: dict[str, list[ReglaActiva]] = {}  # frase → reglas que la dicen (dos reglas con la misma frase, una vez)
    for r, c in (decisiva, *resto):
        causas.setdefault(c.motivo or c.detalle or r.nombre, []).append(r)
    orden = list(causas)
    primera = orden[0]
    hechos = [f for f in orden[1:] if any(r.si_falla == Resultado.NO_PAGAR for r in causas[f])]
    texto = {}
    if regla.nombre in REVISION and hechos:
        orden = [*hechos, primera, *(f for f in orden[1:] if f not in hechos)]
        texto[primera] = "además lo revisa una persona: " + _en_minuscula(primera)
    elif regla.si_falla == Resultado.ESCALAR and all(r.nombre in REVISION for r, _ in fallidas):
        texto[primera] = "Cumple la norma; se escala porque " + _en_minuscula(primera)
    visibles, ocultas = orden[:MAX_CAUSAS], orden[MAX_CAUSAS:]
    motivo = "; ".join(texto.get(f, f) for f in visibles)
    if ocultas:
        n = sum(len(causas[f]) for f in ocultas)
        motivo += f" (y {n} comprobación más)" if n == 1 else f" (y {n} comprobaciones más)"
    return motivo


@dataclass(frozen=True)
class Norma:
    version: str
    reglas: tuple[ReglaActiva, ...]
    divisas: TiposDeCambio = field(default_factory=TiposDeCambio)  # normas/divisas.toml, junto a la norma

    @classmethod
    def desde_toml(cls, ruta: Path) -> Norma:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
        activas = tuple(
            ReglaActiva(nombre, Resultado(conf["si_falla"]), conf.get("params", {}), conf.get("prioridad", 0))
            for nombre, conf in datos["reglas"].items()
        )
        for r in activas:
            reglas.obtener(r.nombre)  # falla al cargar si la norma pide una regla inexistente
        tabla = ruta.with_name("divisas.toml")
        divisas = TiposDeCambio.desde_datos(tomllib.loads(tabla.read_text(encoding="utf-8"))) if tabla.exists() else TiposDeCambio()
        return cls(datos["version"], activas, divisas)

    def evaluar(self, factura: Factura, refs: Referencias) -> Decision:
        # Los tipos de cambio llegan a las reglas como un parámetro más de la norma.
        comprobaciones = tuple(
            reglas.obtener(r.nombre)(factura, refs, {**r.params, "divisas": self.divisas}) for r in self.reglas
        )
        fallidas = [(r, c) for r, c in zip(self.reglas, comprobaciones) if not c.ok]
        if fallidas:
            # Manda la de mayor prioridad y, a igual prioridad, la más grave; entre iguales, la primera de la norma.
            decisiva = max(fallidas, key=lambda par: (par[0].prioridad, GRAVEDAD[par[0].si_falla]))
            resultado, motivo = decisiva[0].si_falla, motivo_de(fallidas, decisiva)
        else:
            resultado, motivo = Resultado.PAGAR, f"Cumple la norma {self.version}"
        return Decision(
            file_id=factura.file_id,
            resultado=resultado,
            motivo=motivo,
            norma=self.version,
            comprobaciones=comprobaciones,
            pedido=factura.pedido,
            alertas=tuple(dict.fromkeys((*factura.alertas, *(f"Nota: {n.texto[:400]}" for n in factura.notas)))),
        )
