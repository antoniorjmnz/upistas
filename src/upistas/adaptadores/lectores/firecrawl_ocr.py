"""OCR de escaneados con Firecrawl /parse.

Firecrawl no acepta imágenes sueltas: el PNG de la página se envuelve en un PDF de una
sola página y se sube a /v2/parse con mode "ocr". Usa httpx (ya es dependencia), así que
no necesita extra ni SDK propio. Fal sigue siendo el proveedor por defecto; este se elige
con OCR_PROVIDER=firecrawl y FIRECRAWL_API_KEY.
"""
from __future__ import annotations

import json
import re

import pymupdf

from upistas.puertos import LecturaFallida


class FirecrawlOCR:
    nombre = "firecrawl"
    ruta = "firecrawl_ocr"
    modelo = "firecrawl/parse"

    def __init__(self, api_key: str, base_url: str = "https://api.firecrawl.dev",
                 timeout: float = 60, cliente=None):
        self.base_url = base_url.rstrip("/")
        if cliente is not None:
            self.cliente = cliente
        elif api_key:
            import httpx

            self.cliente = httpx.Client(
                timeout=timeout,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        else:
            self.cliente = None

    def __call__(self, imagen: bytes) -> str:
        if self.cliente is None:
            raise LecturaFallida("OCR con Firecrawl no disponible: falta FIRECRAWL_API_KEY")
        try:
            pdf_bytes = _imagen_a_pdf(imagen)
            respuesta = self.cliente.post(
                f"{self.base_url}/v2/parse",
                files={"file": ("pagina.pdf", pdf_bytes, "application/pdf")},
                data={"options": json.dumps({"parsers": [{"type": "pdf", "mode": "ocr", "pages": True}]})},
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
        except LecturaFallida:
            raise
        except Exception as exc:
            raise LecturaFallida(f"API de documentos no disponible: {type(exc).__name__}") from exc
        if not isinstance(datos, dict) or not datos.get("success"):
            raise LecturaFallida("Respuesta OCR inválida")
        paginas = (datos.get("data") or {}).get("pages") or []
        texto = (paginas[0].get("markdown") if paginas and isinstance(paginas[0], dict) else None) \
            or (datos.get("data") or {}).get("markdown") or ""
        if not texto.strip():
            raise LecturaFallida("OCR sin texto")
        return _markdown_a_texto(texto)


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
    """El PNG de la página, dentro de un PDF de una página del mismo tamaño."""
    pix = pymupdf.Pixmap(imagen)
    with pymupdf.open() as doc:
        pagina = doc.new_page(width=pix.width, height=pix.height)
        pagina.insert_image(pagina.rect, stream=imagen)
        return doc.tobytes()
