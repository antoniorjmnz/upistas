# Generado por scripts/gen_contracts.py desde contracts/. No editar a mano.

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class Result(Enum):
    PAGAR = 'PAGAR'
    NO_PAGAR = 'NO_PAGAR'
    ESCALAR = 'ESCALAR'


class Regla(BaseModel):
    id: Annotated[str, Field(description='p.ej. R1_nif_iban')]
    ok: bool
    detalle: str | None = None


class Decision(BaseModel):
    file_id: str
    result: Result
    motivo: Annotated[str | None, Field(description='Frase legible para Alberto')] = (
        None
    )
    norma: Annotated[
        str | None, Field(description='Versión de la norma aplicada, p.ej. v3')
    ] = None
    reglas: list[Regla] | None = None
    pedido: str | None = None
    run_id: str | None = None
