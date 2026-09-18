"""La norma de pagos como datos: qué reglas aplican y qué pasa si falla cada una."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from upistas.dominio import reglas
from upistas.dominio.modelos import GRAVEDAD, Decision, Factura, Referencias, Resultado


@dataclass(frozen=True)
class ReglaActiva:
    nombre: str
    si_falla: Resultado
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Norma:
    version: str
    reglas: tuple[ReglaActiva, ...]

    @classmethod
    def desde_toml(cls, ruta: Path) -> Norma:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
        activas = tuple(
            ReglaActiva(nombre, Resultado(conf["si_falla"]), conf.get("params", {}))
            for nombre, conf in datos["reglas"].items()
        )
        for r in activas:
            reglas.obtener(r.nombre)  # falla al cargar si la norma pide una regla inexistente
        return cls(datos["version"], activas)

    def evaluar(self, factura: Factura, refs: Referencias) -> Decision:
        comprobaciones = tuple(
            reglas.obtener(r.nombre)(factura, refs, r.params) for r in self.reglas
        )
        resultado = Resultado.PAGAR
        motivos = []
        for regla_activa, c in zip(self.reglas, comprobaciones):
            if not c.ok:
                motivos.append(c.detalle or regla_activa.nombre)
                if GRAVEDAD[regla_activa.si_falla] > GRAVEDAD[resultado]:
                    resultado = regla_activa.si_falla
        return Decision(
            file_id=factura.file_id,
            resultado=resultado,
            motivo="; ".join(motivos) if motivos else f"Cumple la norma {self.version}",
            norma=self.version,
            comprobaciones=comprobaciones,
            pedido=factura.pedido,
        )
