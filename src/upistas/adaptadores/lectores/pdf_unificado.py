from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf

from upistas.adaptadores.lectores.campos import MODELO_OCR, extraer_campos
from upistas.puertos import DocumentoInspeccionado, LecturaFallida

VERSION = "unificado-4"


def texto_util(texto: str) -> bool:
    palabras = re.findall(r"\w+", texto)
    etiquetas = sum(p in texto.lower() for p in ("factura", "total", "iva", "nif", "cif", "pedido", "iban", "fecha"))
    return len(texto.strip()) >= 80 and len(palabras) >= 10 and (etiquetas >= 2 or len(palabras) >= 40)


def _campos_insuficientes(pagina: dict) -> bool:
    extraida = extraer_campos("pagina", [{"page": pagina.get("page", 1), "route": pagina.get("route", "fal_ocr"),
                                         "text": pagina.get("text", ""), "error": pagina.get("error")}])
    if extraida.errores:
        return True
    return any(getattr(extraida.campos, c).valor is None for c in ("nif", "iban", "pedido", "fecha", "base", "iva", "total"))


def _discrepancias(pagina: dict) -> list[str]:
    ocr, vision = pagina.get("text_ocr") or "", pagina.get("text_vision") or ""
    if not ocr.strip() or not vision.strip():
        return []
    indice = pagina.get("page", 1)
    a = extraer_campos("ocr", [{"page": indice, "route": "fal_ocr", "text": ocr}])
    b = extraer_campos("vision", [{"page": indice, "route": "vision_llm", "text": vision}])
    avisos = []
    for nombre in ("numero_factura", "nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total"):
        ca, cb = getattr(a.campos, nombre), getattr(b.campos, nombre)
        if ca is None or cb is None:
            continue
        va, vb = ca.valor, cb.valor
        if va is not None and vb is not None and va != vb:
            avisos.append(f"Discrepancia OCR/visión en {nombre}")
    return avisos


class LectorPdfUnificado:
    nombre = "pdf_unificado"

    def __init__(self, ocr: Callable[[bytes], str] | None = None, vision: Callable[[bytes], str] | None = None,
                 cache_dir: Path | None = None):
        self.ocr = ocr
        self.vision = vision
        self.cache_dir = cache_dir

    def _clave(self, sha: str) -> str:
        vision = getattr(self.vision, "version", "vision") if self.vision else "no-vision"
        return f"{sha}-{VERSION}-{'ocr' if self.ocr else 'nativo'}-{vision}"

    def acepta(self, ruta: Path | DocumentoInspeccionado) -> bool:
        return ruta.legible if isinstance(ruta, DocumentoInspeccionado) else ruta.suffix.lower() == ".pdf"

    def leer(self, ruta: Path | DocumentoInspeccionado):
        inspeccion = ruta if isinstance(ruta, DocumentoInspeccionado) else None
        ruta = Path(inspeccion.ruta) if inspeccion else ruta
        try:
            if inspeccion and not inspeccion.legible:
                raise LecturaFallida(f"Documento {inspeccion.tipo}")
            if ruta.stat().st_size > 25 * 1024 * 1024:
                raise LecturaFallida("PDF superior al límite de 25 MB")
            contenido = ruta.read_bytes()
            sha = hashlib.sha256(contenido).hexdigest()
            if inspeccion and inspeccion.sha256 != sha:
                raise LecturaFallida("El documento cambió después de inspeccionarlo")
            clave = self._clave(sha)
            cache = self.cache_dir / f"{clave}.json" if self.cache_dir else None
            raw = None
            ocr_previo = {}
            if cache and cache.exists():
                try:
                    anterior = json.loads(cache.read_text(encoding="utf-8"))
                    if anterior.get("status") in ("success", "partial") and anterior.get("sha256") == sha:
                        if any(p.get("vision_error") for p in anterior["pages"]):
                            # La visión falló (quizá de forma pasajera): se reintenta sin repetir el OCR que sí respondió.
                            ocr_previo = {p["page"]: p["text_ocr"] for p in anterior["pages"] if p.get("text_ocr")}
                        else:
                            raw = anterior
                except (ValueError, OSError, KeyError, TypeError):
                    pass
            if raw is None:
                raw = self._extraer(contenido, sha, ocr_previo)
                if cache and raw.get("status") != "failed":
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache.parent, suffix=".tmp", delete=False) as f:
                        json.dump(raw, f, ensure_ascii=False)
                        temporal = Path(f.name)
                    temporal.replace(cache)
            extraida = extraer_campos(ruta.name, raw["pages"], documento={
                "sha256": sha,
                "tipo": inspeccion.tipo if inspeccion else ("escaneado" if any(p["route"] in ("fal_ocr", "vision_llm") for p in raw["pages"]) else "texto"),
                "paginas": raw["page_count"],
                "bytes": len(contenido),
                "alertas": list(inspeccion.alertas) if inspeccion else [],
            })
            extras = []
            for pagina in raw["pages"]:
                extras.extend(_discrepancias(pagina))
                if pagina.get("vision_error"):
                    extras.append(f"Página {pagina.get('page')}: {pagina['vision_error']}")
            if extras:
                extraida = extraida.model_copy(update={"errores": list(extraida.errores or []) + extras})
            return extraida
        except LecturaFallida:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise LecturaFallida(f"No se pudo leer {ruta.name}: {exc}") from exc

    def _ver(self, imagen: bytes) -> tuple[str, dict]:
        """(texto, uso): un adaptador con `transcribir` informa del modelo y los tokens; un callable simple, solo del texto."""
        transcribir = getattr(self.vision, "transcribir", None)
        return transcribir(imagen) if transcribir else (self.vision(imagen), {})

    def texto_extraido(self, ruta: Path) -> str:
        if self.cache_dir is None:
            return ""
        try:
            sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
            raw = json.loads((self.cache_dir / f"{self._clave(sha)}.json").read_text(encoding="utf-8"))
            return "\n\n".join(pagina["text"] for pagina in raw["pages"])
        except (OSError, ValueError, KeyError):
            return ""

    def _extraer(self, contenido: bytes, sha: str, ocr_previo: dict[int, str] | None = None) -> dict:
        ocr_previo = ocr_previo or {}
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
                        traza["model"] = MODELO_OCR
                        texto_ocr = ocr_previo.get(indice) or self.ocr(imagen)
                        if not isinstance(texto_ocr, str) or not texto_ocr.strip():
                            raise LecturaFallida("OCR sin texto")
                        traza["text"] = texto_ocr
                        traza["text_ocr"] = texto_ocr
                        if self.vision is not None and _campos_insuficientes(traza):
                            try:
                                texto_vision, uso = self._ver(imagen)
                                if not isinstance(texto_vision, str) or not texto_vision.strip():
                                    raise LecturaFallida("Visión sin texto")
                                traza["text_vision"] = texto_vision
                                traza["text"] = texto_vision
                                traza["route"] = "vision_llm"
                                traza["model"] = uso.get("modelo") or getattr(self.vision, "version", None)
                                traza["tokens_in"] = uso.get("tokens_in") or 0
                                traza["tokens_out"] = uso.get("tokens_out") or 0
                            except LecturaFallida as exc:
                                traza["vision_error"] = str(exc)
                            except Exception:
                                traza["vision_error"] = "Respaldo visual no disponible"
                except Exception as exc:
                    traza["error"] = str(exc)
                traza["latency_ms"] = round((time.perf_counter() - inicio) * 1000)
                traza["text_chars"] = len(traza["text"])
                paginas.append(traza)
        errores = sum(p["error"] is not None for p in paginas)
        vision_fallida = any(p.get("vision_error") for p in paginas)
        if errores == len(paginas):
            estado = "failed"
        elif errores or vision_fallida:
            estado = "partial"
        else:
            estado = "success"
        return {
            "schema_version": VERSION,
            "sha256": sha,
            "page_count": len(paginas),
            "pages": paginas,
            "status": estado,
        }
