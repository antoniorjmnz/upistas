from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentTrace(BaseModel):
    filename: str
    sha256: str
    page_count: int


class PageTrace(BaseModel):
    page: int

    # native_text | fal_ocr
    route: str

    text: str
    text_chars: int

    latency_ms: int = 0
    model: str | None = None
    error: str | None = None

    # Ruta de la imagen temporal solo para debugging local.
    # No hace falta persistirla después.
    rendered_image: str | None = None


class RawExtractionResult(BaseModel):
    schema_version: str = "raw-1.0"

    document: DocumentTrace
    pages: list[PageTrace] = Field(default_factory=list)

    # success | partial | failed
    status: str
