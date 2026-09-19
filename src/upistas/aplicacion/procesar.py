"""Caso de uso principal: un documento → una decisión."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.modelos import Decision, Referencias, Resultado
from upistas.dominio.norma import Norma
from upistas.puertos import DocumentoInspeccionado, Inspector, LecturaFallida, LectorDocumento

from upistas.aplicacion.mapeo import a_factura


@dataclass(frozen=True)
class Lectura:
    documento: DocumentoInspeccionado
    extraida: FacturaExtraida | None = None
    intentos: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (lector, por qué no pudo)

    @property
    def motivo_fallo(self) -> str:
        if self.extraida is not None:
            return ""
        if not self.documento.legible:
            return f"documento {self.documento.tipo}: " + ", ".join(self.documento.alertas or ("no se puede leer",))
        if not self.intentos:
            return f"ningún lector acepta un documento de tipo {self.documento.tipo}"
        return "; ".join(f"{lector}: {error}" for lector, error in self.intentos)


def leer_documento(ruta: Path, inspector: Inspector, lectores: Sequence[LectorDocumento]) -> Lectura:
    """Inspecciona una vez y prueba los lectores en orden (del más barato al más caro)."""
    doc = inspector.inspeccionar(ruta)
    if not doc.legible:
        return Lectura(doc)
    intentos: list[tuple[str, str]] = []
    for lector in lectores:
        if not lector.acepta(doc):
            continue
        try:
            return Lectura(doc, lector.leer(doc), tuple(intentos))
        except LecturaFallida as exc:
            intentos.append((lector.nombre, str(exc)))
    return Lectura(doc, None, tuple(intentos))


def decidir(file_id: str, lectura: Lectura | None, refs: Referencias | None, norma: Norma) -> Decision:
    if lectura is None or lectura.extraida is None or refs is None:
        motivo = lectura.motivo_fallo if lectura else "sin lectura"
        return Decision(
            file_id=file_id,
            resultado=Resultado.ESCALAR,
            motivo=f"No se pudo leer la factura ({motivo})",
            norma=norma.version,
            alertas=tuple(lectura.documento.alertas) if lectura else (),
        )
    return norma.evaluar(a_factura(lectura.extraida), refs)
