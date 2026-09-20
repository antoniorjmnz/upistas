from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path

from upistas.adaptadores.lectores.pdf import MAX_BYTES
from upistas.aplicacion.procesar import Lectura
from upistas.config import Settings
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.puertos import DocumentoInspeccionado


def identificar(ruta: Path) -> DocumentoInspeccionado:
    base = DocumentoInspeccionado(ruta.name, str(ruta.resolve()), "", 0, "otro")
    try:
        if not ruta.is_file():
            return replace(base, alertas=("el fichero no existe o no es regular",))
        tamano = ruta.stat().st_size
        if tamano > MAX_BYTES:
            return replace(base, bytes=tamano, alertas=("documento superior al límite de 25 MB",))
        with ruta.open("rb") as fichero:
            contenido = fichero.read(MAX_BYTES + 1)
        if len(contenido) > MAX_BYTES:
            return replace(base, bytes=len(contenido), alertas=("el documento creció por encima del límite de tamaño",))
        return replace(base, sha256=hashlib.sha256(contenido).hexdigest(), bytes=len(contenido),
                       tipo="otro" if contenido else "blanco", alertas=() if contenido else ("fichero vacío",))
    except OSError as exc:
        return replace(base, alertas=(f"no se pudo acceder al documento: {type(exc).__name__}",))


def leer(ruta: Path, configuracion: Settings, documento: DocumentoInspeccionado | None = None) -> Lectura:
    limite = configuracion.lectura_timeout_s
    if not math.isfinite(limite) or limite <= 0:
        raise ValueError("LECTURA_TIMEOUT_S debe ser un número positivo y finito")
    doc = documento or identificar(ruta)
    if doc.alertas:
        return Lectura(doc)

    def fallo(motivo):
        return Lectura(replace(doc, alertas=doc.alertas + (motivo,)), intentos=(("lectura_acotada", motivo),))

    peticion = {
        "ruta": str(ruta.resolve()), "sha256": doc.sha256,
        "ocr": configuracion.usar_ocr, "outputs_dir": str(configuracion.outputs_dir.resolve()),
        "firecrawl_api_key": configuracion.firecrawl_api_key,
        "firecrawl_base_url": configuracion.firecrawl_base_url,
    }
    try:
        proceso = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "upistas.infra.lectura_acotada"],
            input=json.dumps(peticion), capture_output=True, encoding="utf-8",
            timeout=limite, check=False,
        )
    except subprocess.TimeoutExpired:
        return fallo(f"Tiempo de lectura agotado: {limite:g} segundos; proceso detenido")
    except OSError as exc:
        return fallo(f"No se pudo iniciar la lectura: {type(exc).__name__}")
    if proceso.returncode:
        return fallo(f"El proceso de lectura terminó con código {proceso.returncode}")
    try:
        datos = json.loads(proceso.stdout)
        if datos.get("error"):
            return fallo(datos["error"][:500])
        inspeccion = DocumentoInspeccionado(**datos["documento"])
        if inspeccion.sha256 != doc.sha256:
            return fallo("El documento cambió durante la lectura")
        extraida = FacturaExtraida.model_validate(datos["extraida"]) if datos["extraida"] else None
        return Lectura(inspeccion, extraida, tuple(tuple(i) for i in datos["intentos"]))
    except (ValueError, KeyError, TypeError):
        return fallo("El proceso de lectura devolvió una respuesta inválida")


def _ejecutar():
    from upistas.aplicacion.procesar import leer_documento
    from upistas.infra import contenedor

    try:
        peticion = json.load(sys.stdin)
        contenedor.configurar(replace(contenedor.settings, usar_ocr=peticion["ocr"],
                                      outputs_dir=Path(peticion["outputs_dir"]),
                                      firecrawl_api_key=peticion.get("firecrawl_api_key", ""),
                                      firecrawl_base_url=peticion.get("firecrawl_base_url", "https://api.firecrawl.dev")))
        with redirect_stdout(sys.stderr):
            lectura = leer_documento(Path(peticion["ruta"]), contenedor.inspector(), contenedor.lectores())
        respuesta = {
            "documento": asdict(lectura.documento),
            "extraida": lectura.extraida.model_dump(mode="json") if lectura.extraida else None,
            "intentos": list(lectura.intentos),
        }
    except Exception as exc:
        respuesta = {"error": f"Fallo de lectura: {type(exc).__name__}: {str(exc)[:300]}"}
    print(json.dumps(respuesta, ensure_ascii=True))


if __name__ == "__main__":
    _ejecutar()
