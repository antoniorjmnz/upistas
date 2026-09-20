"""La norma de pagos como datos: qué reglas aplican y qué pasa si falla cada una."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from upistas.dominio import reglas
from upistas.dominio.divisas import TiposDeCambio
from upistas.dominio.modelos import GRAVEDAD, Decision, Factura, Referencias, Resultado


@dataclass(frozen=True)
class ReglaActiva:
    nombre: str
    si_falla: Resultado
    params: dict[str, Any] = field(default_factory=dict)
    prioridad: int = 0


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
        resultado = Resultado.PAGAR
        prioridad = (-1, 0)
        motivos = []
        for regla_activa, c in zip(self.reglas, comprobaciones):
            if not c.ok:
                motivos.append(c.detalle or regla_activa.nombre)
                candidata = (regla_activa.prioridad, GRAVEDAD[regla_activa.si_falla])
                if candidata > prioridad:
                    resultado = regla_activa.si_falla
                    prioridad = candidata
        return Decision(
            file_id=factura.file_id,
            resultado=resultado,
            motivo="; ".join(motivos) if motivos else f"Cumple la norma {self.version}",
            norma=self.version,
            comprobaciones=comprobaciones,
            pedido=factura.pedido,
            alertas=tuple(dict.fromkeys((*factura.alertas, *(f"Nota: {n.texto[:400]}" for n in factura.notas)))),
        )
