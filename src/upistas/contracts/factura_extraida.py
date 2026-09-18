# Generado por scripts/gen_contracts.py desde contracts/. No editar a mano.

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Metodo(Enum):
    texto_determinista = 'texto_determinista'
    texto_llm = 'texto_llm'
    vision_llm = 'vision_llm'


class Linea(BaseModel):
    concepto: str
    importe: float


class Checks(BaseModel):
    total_cuadra: Annotated[
        bool | None, Field(description='base + iva == total (±0,01)')
    ] = None
    lineas_cuadran: Annotated[
        bool | None,
        Field(description='suma(lineas) == base (±0,01); null si no hay líneas'),
    ] = None


class Coste(BaseModel):
    tokens_in: int | None = None
    tokens_out: int | None = None
    eur: float | None = None
    modelo: str | None = None


class CampoStr(BaseModel):
    valor: str | None
    confianza: Annotated[float, Field(ge=0.0, le=1.0)]
    fuente: Annotated[
        str | None, Field(description='Texto literal del que se sacó')
    ] = None


class CampoNum(BaseModel):
    valor: float | None
    confianza: Annotated[float, Field(ge=0.0, le=1.0)]
    fuente: str | None = None


class Campos(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    numero_factura: CampoStr | None = None
    proveedor_nombre: CampoStr | None = None
    nif: CampoStr
    iban: Annotated[CampoStr, Field(description='Sin espacios, mayúsculas')]
    pedido: Annotated[CampoStr, Field(description='PO-AAAA-NNNN')]
    fecha: Annotated[CampoStr, Field(description='ISO AAAA-MM-DD')]
    base: CampoNum
    iva_pct: CampoNum
    iva: CampoNum
    total: CampoNum


class FacturaExtraida(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    file_id: Annotated[str, Field(description='Nombre del PDF tal cual en La Caja')]
    metodo: Annotated[Metodo, Field(description='Cómo se obtuvo la mayoría de campos')]
    campos: Campos
    lineas: list[Linea] | None = None
    checks: Annotated[
        Checks, Field(description='Checksums internos de la propia factura')
    ]
    coste: Coste | None = None
    errores: list[str] | None = None
