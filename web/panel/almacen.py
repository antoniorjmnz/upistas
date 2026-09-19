"""Dónde van los PDF que Alberto sube por la web.

Cada contenido se guarda una sola vez, con su huella por nombre (`almacen/facturas/<sha256>.pdf`):
si vuelve a subir la misma factura no se duplica, se reutiliza la que ya estaba. El nombre con el
que llegó se conserva aparte, para que Alberto reconozca sus facturas.
"""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from django.conf import settings

from web.panel.models import Documento

CARPETA = "facturas"
FIRMA_PDF = b"%PDF"


class Factura(NamedTuple):
    file_id: str  # el nombre con el que llegó, único dentro del lote
    ruta: Path  # dónde quedó guardada: la que leerá el pipeline y servirá la web


class Guardado(NamedTuple):
    facturas: list[Factura]
    errores: list[str]  # lo que no se pudo guardar, dicho para Alberto


def guardar(lote: str, ficheros: Iterable) -> Guardado:
    """Guarda los PDF que suben (sueltos o dentro de un zip) y dice cuáles no valían."""
    carpeta = Path(settings.MEDIA_ROOT) / CARPETA
    carpeta.mkdir(parents=True, exist_ok=True)
    usados = dict(Documento.objects.filter(lote=lote).values_list("file_id", "sha256"))
    facturas: list[Factura] = []
    errores: list[str] = []
    for fichero in ficheros:
        for nombre, datos in _desempaquetar(fichero, errores):
            if not datos.startswith(FIRMA_PDF):
                errores.append(f"«{nombre}» no es un PDF: no se ha guardado.")
                continue
            huella = hashlib.sha256(datos).hexdigest()
            ruta = carpeta / f"{huella}.pdf"
            if not ruta.exists():
                ruta.write_bytes(datos)
            facturas.append(Factura(_nombre_libre(nombre, huella, usados), ruta))
    return Guardado(facturas, errores)


def _desempaquetar(fichero, errores: list[str]) -> Iterator[tuple[str, bytes]]:
    """Un fichero subido da un PDF; un zip da todos los que trae dentro."""
    nombre = _solo_el_nombre(fichero.name)
    if not nombre.lower().endswith(".zip"):
        yield nombre, fichero.read()
        return
    try:
        with zipfile.ZipFile(fichero) as paquete:
            miembros = [m for m in paquete.infolist() if not m.is_dir()]
            pdfs = [m for m in miembros if _solo_el_nombre(m.filename).lower().endswith(".pdf")]
            if not pdfs:
                errores.append(f"«{nombre}» no trae ninguna factura en PDF.")
            for miembro in pdfs:
                yield _solo_el_nombre(miembro.filename), paquete.read(miembro)
    except zipfile.BadZipFile:
        errores.append(f"«{nombre}» no se puede abrir: el zip está dañado.")


def _solo_el_nombre(nombre: str) -> str:
    """El nombre del fichero y nada más: nada de carpetas, unidades ni «..»."""
    limpio = PurePosixPath((nombre or "").replace("\\", "/")).name
    return "" if limpio in ("", ".", "..") else limpio


def _nombre_libre(nombre: str, huella: str, usados: dict[str, str]) -> str:
    """El nombre con el que llegó; si en el lote ya hay otra factura distinta con ese nombre, un sufijo."""
    nombre = nombre or f"{huella[:12]}.pdf"
    candidato, base = nombre, Path(nombre)
    numero = 1
    while usados.get(candidato, huella) != huella:
        numero += 1
        candidato = f"{base.stem}-{numero}{base.suffix}"
    usados[candidato] = huella
    return candidato
