from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf

from upistas.adaptadores.lectores.campos import extraer_campos
from upistas.puertos import LecturaFallida

VERSION = "unificado-3"


def texto_util(texto: str) -> bool:
    palabras = re.findall(r"\w+", texto)
    etiquetas = sum(p in texto.lower() for p in ("factura", "total", "iva", "nif", "cif", "pedido", "iban", "fecha"))
    return len(texto.strip()) >= 80 and len(palabras) >= 10 and (etiquetas >= 2 or len(palabras) >= 40)


class LectorPdfUnificado:
    nombre = "pdf_unificado"

    def __init__(self, ocr: Callable[[bytes], str] | None = None, cache_dir: Path | None = None):
        self.ocr = ocr
        self.cache_dir = cache_dir

    def acepta(self, ruta: Path) -> bool:
        return ruta.suffix.lower() == ".pdf"

    def leer(self, ruta: Path):
        try:
            if ruta.stat().st_size > 25 * 1024 * 1024:
                raise LecturaFallida("PDF superior al límite de 25 MB")
            contenido = ruta.read_bytes()
            sha = hashlib.sha256(contenido).hexdigest()
            clave = f"{sha}-{VERSION}-{'ocr' if self.ocr else 'nativo'}"
            cache = self.cache_dir / f"{clave}.json" if self.cache_dir else None
            raw = None
            if cache and cache.exists():
                try:
                    anterior = json.loads(cache.read_text(encoding="utf-8"))
                    if anterior.get("status") == "success" and anterior.get("sha256") == sha:
                        raw = anterior
                except (ValueError, OSError):
                    pass
            if raw is None:
                raw = self._extraer(contenido, sha)
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache.parent, suffix=".tmp", delete=False) as f:
                        json.dump(raw, f, ensure_ascii=False)
                        temporal = Path(f.name)
                    temporal.replace(cache)
            return extraer_campos(ruta.name, raw["pages"], documento={
                "sha256": sha,
                "tipo": "escaneado" if any(p["route"] == "fal_ocr" for p in raw["pages"]) else "texto",
                "paginas": raw["page_count"],
                "bytes": len(contenido),
            })
        except LecturaFallida:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise LecturaFallida(f"No se pudo leer {ruta.name}: {exc}") from exc

    def texto_extraido(self, ruta: Path) -> str:
        if self.cache_dir is None:
            return ""
        try:
            sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
            clave = f"{sha}-{VERSION}-{'ocr' if self.ocr else 'nativo'}"
            raw = json.loads((self.cache_dir / f"{clave}.json").read_text(encoding="utf-8"))
            return "\n\n".join(pagina["text"] for pagina in raw["pages"])
        except (OSError, ValueError, KeyError):
            return ""

    def _extraer(self, contenido: bytes, sha: str) -> dict:
        paginas = []
        with pymupdf.open(stream=contenido, filetype="pdf") as pdf:
            if pdf.needs_pass or not 0 < len(pdf) <= 50:
                raise LecturaFallida("PDF cifrado, vacío o con más de 50 páginas")
            for indice, pagina in enumerate(pdf, 1):
                inicio = time.perf_counter()
                traza = {"page": indice, "route": "native_text", "text": "", "error": None, "model": None}
                try:
                    texto = pagina.get_text("text").strip()
                    if texto_util(texto):
                        traza["text"] = texto
                    else:
                        traza["route"] = "fal_ocr"
                        if self.ocr is None:
                            raise LecturaFallida("Página sin texto útil; OCR no habilitado")
                        if pagina.rect.width * pagina.rect.height * (200 / 72) ** 2 > 16_000_000:
                            raise LecturaFallida("Página demasiado grande para OCR")
                        imagen = pagina.get_pixmap(dpi=200, alpha=False).tobytes("png")
                        traza["model"] = "fal-ai/got-ocr/v2"
                        texto_ocr = self.ocr(imagen)
                        if not isinstance(texto_ocr, str) or not texto_ocr.strip():
                            raise LecturaFallida("OCR sin texto")
                        traza["text"] = texto_ocr
                except Exception as exc:
                    traza["error"] = str(exc)
                traza["latency_ms"] = round((time.perf_counter() - inicio) * 1000)
                traza["text_chars"] = len(traza["text"])
                paginas.append(traza)
        errores = sum(p["error"] is not None for p in paginas)
        return {
            "schema_version": VERSION,
            "sha256": sha,
            "page_count": len(paginas),
            "pages": paginas,
            "status": "success" if not errores else "failed" if errores == len(paginas) else "partial",
        }
