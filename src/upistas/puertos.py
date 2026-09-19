"""Puertos: lo que la aplicación necesita del mundo exterior, sin decir cómo se consigue.

Cada puerto tiene una o varias implementaciones en `adaptadores/`. Para soportar algo nuevo
(emails, otro ERP, otro proveedor de LLM) se añade un adaptador; el dominio y la aplicación
no cambian.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.modelos import Asiento, Pedido, Proveedor

# --- Documentos -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentoInspeccionado:
    """Un fichero abierto con cuidado: qué es y qué trae de raro. Lo producen los inspectores."""

    file_id: str
    ruta: str
    sha256: str
    bytes: int
    tipo: str  # texto | escaneado | blanco | roto | cifrado | otro
    paginas: int = 0
    texto_por_pagina: tuple[str, ...] = ()
    alertas: tuple[str, ...] = field(default_factory=tuple)

    @property
    def legible(self) -> bool:
        return self.tipo in ("texto", "escaneado")


class Inspector(Protocol):
    def inspeccionar(self, ruta: Path) -> DocumentoInspeccionado: ...


class LecturaFallida(Exception):
    """El lector no pudo sacar la factura de este documento. El siguiente lector lo intentará."""


class LectorDocumento(Protocol):
    """Convierte un documento (PDF, escaneo, email...) en una factura extraída."""

    nombre: str

    def acepta(self, doc: DocumentoInspeccionado) -> bool: ...

    def leer(self, doc: DocumentoInspeccionado) -> FacturaExtraida: ...


class FuenteMaestro(Protocol):
    """Datos de proveedores y pedidos (hoy: el Excel de Alberto)."""

    version: str  # cambia si cambia el fichero: forma parte de la versión de los datos

    def proveedores(self) -> list[Proveedor]: ...

    def pedidos(self) -> list[Pedido]: ...

    def marcados_para_revisar(self) -> frozenset[str]:
        """Pedidos que Alberto apuntó a mano para mirar (hoja pendiente_revisar)."""
        ...


class FuenteERP(Protocol):
    """Asientos contables oficiales con los que decidir (hoy: la copia local del ERP)."""

    def asientos(self) -> list[Asiento]: ...


# --- ERP remoto y su copia local -------------------------------------------------------------


class ErrorERP(Exception):
    """El ERP no respondió bien ni después de reintentar."""


@dataclass(frozen=True)
class EstadisticasDescarga:
    peticiones: int = 0
    reintentos_ora: int = 0  # ORA-00600: error interno, se reintenta la misma consulta
    esperas_429: int = 0  # ERP-429: demasiadas peticiones, se espera Retry-After
    relogins: int = 0  # SES-401: sesión caducada, se vuelve a identificar
    errores_red: int = 0
    segundos: float = 0.0


@dataclass(frozen=True)
class DescargaERP:
    asientos: tuple[Asiento, ...]
    lote2_cargado: bool
    estadisticas: EstadisticasDescarga


class ClienteERP(Protocol):
    """El ERP de Alberto. Solo se lee: no tiene forma de escribir."""

    def descargar(self) -> DescargaERP: ...


@dataclass(frozen=True)
class Sincronizacion:
    """Una descarga del ERP, haya ido bien o mal. Es el historial que ve Alberto."""

    inicio: datetime
    fin: datetime
    ok: bool
    version: str | None = None
    n_asientos: int = 0
    lote2_cargado: bool = False
    estadisticas: EstadisticasDescarga = field(default_factory=EstadisticasDescarga)
    error: str | None = None
    nuevos: int = 0  # respecto a la versión anterior
    modificados: int = 0
    eliminados: int = 0


class AlmacenERP(Protocol):
    """Copia local y versionada de los asientos, y el historial de sincronizaciones."""

    def registrar(self, sincronizacion: Sincronizacion, asientos: tuple[Asiento, ...] | None) -> None:
        """Guarda la sincronización y, si es una versión nueva, sus asientos."""
        ...

    def asientos(self, version: str | None = None) -> list[Asiento]:
        """Asientos de una versión; sin versión, los de la última descarga correcta."""
        ...

    def ultima(self, solo_correctas: bool = True) -> Sincronizacion | None: ...


# --- IA ---------------------------------------------------------------------------------------


class RespuestaInvalida(Exception):
    """El modelo respondió algo que no es el JSON que se le pidió."""


class ModeloLenguaje(Protocol):
    """Un LLM que devuelve JSON conforme a un esquema. Solo extrae; nunca decide pagos."""

    nombre: str

    def extraer_json(self, instrucciones: str, texto: str | None = None, imagenes: list[bytes] | None = None) -> tuple[dict, dict]:
        """Devuelve (json, uso). `uso` trae tokens_in, tokens_out, modelo y segundos."""
        ...


# --- Lo que se guarda: lecturas, ejecuciones y decisiones -----------------------------------


@dataclass(frozen=True)
class RegistroLectura:
    """La lectura de un documento tal como se guarda: es la caché y la traza a la vez."""

    lote: str
    file_id: str
    ruta: str
    sha256: str
    bytes: int
    tipo: str
    paginas: int
    alertas: tuple[str, ...]
    extraida: FacturaExtraida | None
    intentos: tuple[tuple[str, str], ...] = ()
    segundos: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    coste_eur: float = 0.0
    modelo: str = ""
    cuando: datetime | None = None
    version: str = ""  # versión de los lectores con la que se leyó; si cambia, se vuelve a leer

    @property
    def leida(self) -> bool:
        return self.extraida is not None

    @property
    def metodo(self) -> str:
        return self.extraida.metodo.value if self.extraida else "ninguno"

    def documento(self) -> DocumentoInspeccionado:
        return DocumentoInspeccionado(self.file_id, self.ruta, self.sha256, self.bytes, self.tipo, self.paginas, (), self.alertas)


class RepositorioLecturas(Protocol):
    def guardar(self, registro: RegistroLectura) -> None: ...

    def por_sha(self, sha256: str, version: str) -> RegistroLectura | None:
        """La lectura de ese contenido con esa versión de lectores, venga del lote que venga."""
        ...

    def del_lote(self, lote: str, version: str | None = None) -> list[RegistroLectura]:
        """Los documentos del lote con su lectura (la de esa versión, o la más reciente)."""
        ...


@dataclass(frozen=True)
class Ejecucion:
    """Una pasada completa por un lote con una norma y una versión de los datos."""

    id: int
    lote: str
    norma: str
    version_erp: str
    version_excel: str
    inicio: datetime
    fin: datetime | None = None
    estado: str = "en_curso"  # en_curso | terminada | interrumpida
    hardware: dict = field(default_factory=dict)
    resumen: dict = field(default_factory=dict)

    @property
    def version_datos(self) -> str:
        return f"{self.version_erp}+{self.version_excel}"


@dataclass(frozen=True)
class DecisionGuardada:
    file_id: str
    resultado: str
    motivo: str
    pedido: str | None
    metodo: str
    outcome: dict  # la línea de outcomes.jsonl, con reglas y alertas
    notas: tuple[dict, ...] = ()
    alertas: tuple[str, ...] = ()


class RepositorioDecisiones(Protocol):
    def iniciar_ejecucion(self, lote: str, norma: str, version_erp: str, version_excel: str, hardware: dict) -> Ejecucion: ...

    def guardar_decisiones(self, ejecucion_id: int, decisiones: Sequence[DecisionGuardada]) -> None: ...

    def terminar_ejecucion(self, ejecucion_id: int, resumen: dict) -> Ejecucion: ...

    def ejecuciones(self, lote: str | None = None) -> list[Ejecucion]:
        """De la más reciente a la más antigua."""
        ...

    def decisiones(self, ejecucion_id: int) -> list[DecisionGuardada]: ...

    def pedidos_aprobados(self, excepto_lote: str) -> frozenset[str]:
        """Pedidos aprobados para pago en la última ejecución terminada de cada otro lote,
        más los aprobados a mano por una persona. El ERP no se entera de lo que pagamos:
        esta es nuestra memoria para no pagar dos veces."""
        ...
