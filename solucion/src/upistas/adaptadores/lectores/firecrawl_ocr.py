"""OCR de escaneados con Firecrawl /parse.

Firecrawl no acepta imágenes sueltas: el PNG de la página se envuelve en un PDF de una
sola página y se sube a /v2/parse con mode "ocr". Usa httpx (ya es dependencia), así que
no necesita extra ni SDK propio. Se activa con --ocr / usar_ocr y FIRECRAWL_API_KEY.

El plan limita la concurrencia y corta conexiones a la vez (RemoteProtocolError, 429, 5xx):
como cada documento se lee en su propio proceso, las llamadas se serializan con un cerrojo
de fichero (`cerrojo`) y los transitorios que queden se reintentan con backoff. Los
deterministas (4xx, respuesta sin texto o inválida) no se reintentan.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

import httpx
import pymupdf

from upistas.puertos import LecturaFallida


class FirecrawlOCR:
    nombre = "firecrawl"
    ruta = "firecrawl_ocr"
    modelo = "firecrawl/parse"

    def __init__(self, api_key: str, base_url: str = "https://api.firecrawl.dev",
                 timeout: float = 120, cliente=None, intentos: int = 3, espera_base: float = 2.0,
                 dormir=None, cerrojo: Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.intentos = intentos
        self.espera_base = espera_base
        self.dormir = dormir or time.sleep
        self.cerrojo = cerrojo
        if cliente is not None:
            self.cliente = cliente
        elif api_key:
            self.cliente = httpx.Client(
                timeout=timeout,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        else:
            self.cliente = None

    def __call__(self, imagen: bytes) -> str:
        if self.cliente is None:
            raise LecturaFallida("OCR con Firecrawl no disponible: falta FIRECRAWL_API_KEY")
        pdf = _imagen_a_pdf(imagen)
        with _exclusivo(self.cerrojo):
            datos = self._llamar(pdf)
        if not datos.get("success"):
            detalle = str(datos.get("error") or "")[:200]
            raise LecturaFallida(f"Respuesta OCR inválida{': ' + detalle if detalle else ''}")
        paginas = (datos.get("data") or {}).get("pages") or []
        texto = (paginas[0].get("markdown") if paginas and isinstance(paginas[0], dict) else None) \
            or (datos.get("data") or {}).get("markdown") or ""
        if not texto.strip():
            raise LecturaFallida("OCR sin texto")
        return _markdown_a_texto(texto)

    def _llamar(self, pdf_bytes: bytes) -> dict:
        """Un POST a /v2/parse. Transitorios (transporte, 429, 5xx) se reintentan; 4xx y JSON roto, no."""
        ultimo: Exception | None = None
        for intento in range(1, self.intentos + 1):
            espera = self.espera_base * intento
            try:
                respuesta = self.cliente.post(
                    f"{self.base_url}/v2/parse",
                    files={"file": ("pagina.pdf", pdf_bytes, "application/pdf")},
                    data={"options": json.dumps({"parsers": [{"type": "pdf", "mode": "ocr", "pages": True}]})},
                )
            except httpx.TransportError as exc:
                ultimo = exc
            except Exception as exc:
                raise LecturaFallida(f"API de documentos no disponible: {type(exc).__name__}") from exc
            else:
                if respuesta.status_code == 429 or respuesta.status_code >= 500:
                    ultimo = RuntimeError(f"HTTP {respuesta.status_code}")
                    retry_after = respuesta.headers.get("retry-after") or ""
                    if retry_after.replace(".", "", 1).isdigit():
                        espera = min(float(retry_after), 30)
                elif respuesta.status_code >= 400:
                    raise LecturaFallida(f"API de documentos: HTTP {respuesta.status_code}")
                else:
                    try:
                        datos = respuesta.json()
                    except Exception as exc:
                        raise LecturaFallida("Respuesta OCR inválida") from exc
                    if not isinstance(datos, dict):
                        raise LecturaFallida("Respuesta OCR inválida")
                    return datos
            if intento < self.intentos:
                self.dormir(espera)
        raise LecturaFallida(f"API de documentos no disponible: {type(ultimo).__name__}") from ultimo


def _exclusivo(ruta: Path | None):
    """Una llamada OCR a la vez entre todos los procesos del lote: el plan corta la concurrencia."""
    if ruta is None:
        return nullcontext()
    return _cerrojo_fichero(ruta)


@contextmanager
def _cerrojo_fichero(ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a+b") as f:
        try:
            import msvcrt

            f.seek(0)
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.5)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except ImportError:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _markdown_a_texto(texto: str) -> str:
    """Firecrawl devuelve markdown; el extractor determinista espera líneas de texto plano.

    Quita encabezados (`##`), negritas y las barras de las tablas, de modo que
    `| Servicio mensual | 683,33 |` quede como `Servicio mensual 683,33`.
    """
    lineas = []
    for linea in texto.splitlines():
        linea = re.sub(r"^#+\s*", "", linea)
        linea = re.sub(r"\|?\s*-{3,}\s*", " ", linea)  # separadores de tabla | --- |
        linea = linea.replace("**", "").replace("__", "")
        linea = re.sub(r"\s*\|\s*", " ", linea)
        lineas.append(re.sub(r"\s{2,}", " ", linea).strip())
    return "\n".join(lineas).strip()


def _imagen_a_pdf(imagen: bytes) -> bytes:
    """La página, dentro de un PDF de una página del mismo tamaño.

    Va como JPEG: con el PNG, pymupdf lo incrusta sin comprimir (11 MB por página a 200 ppp) y Firecrawl
    corta la conexión; en JPEG son unos 60 KB y contesta en cinco segundos."""
    pix = pymupdf.Pixmap(imagen)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    jpeg = pix.tobytes("jpeg", jpg_quality=80)
    with pymupdf.open() as doc:
        pagina = doc.new_page(width=pix.width, height=pix.height)
        pagina.insert_image(pagina.rect, stream=jpeg)
        return doc.tobytes()
