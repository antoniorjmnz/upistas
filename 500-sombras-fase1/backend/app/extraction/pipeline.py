from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf as fitz

from .fal_ocr import FAL_MODEL, ocr_image
from .pdf_reader import route_pdf
from .schemas import (
    DocumentTrace,
    PageTrace,
    RawExtractionResult,
)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def count_pages(path: str) -> int:
    document = fitz.open(path)

    try:
        return document.page_count
    finally:
        document.close()


def extract_raw_document(
    pdf_path: str,
) -> RawExtractionResult:
    """
    Primera fase completa:

    PDF
      -> route por página
      -> native text o Fal
      -> RawExtractionResult
    """

    path = Path(pdf_path)

    routed_pages = route_pdf(
        str(path)
    )

    traces: list[PageTrace] = []
    errors = 0

    for page in routed_pages:
        print(
            f"[PAGE {page.page_number}] route={page.route}"
        )

        if page.route == "native_text":
            text = page.text or ""

            traces.append(
                PageTrace(
                    page=page.page_number,
                    route="native_text",
                    text=text,
                    text_chars=len(text),
                    latency_ms=0,
                    model=None,
                    error=None,
                    rendered_image=None,
                )
            )

            continue

        try:
            result = ocr_image(
                page.image_path or ""
            )

            text = result["text"]

            traces.append(
                PageTrace(
                    page=page.page_number,
                    route="fal_ocr",
                    text=text,
                    text_chars=len(text),
                    latency_ms=result["latency_ms"],
                    model=result["model"],
                    error=None,
                    rendered_image=page.image_path,
                )
            )

        except Exception as exc:
            errors += 1

            traces.append(
                PageTrace(
                    page=page.page_number,
                    route="fal_ocr",
                    text="",
                    text_chars=0,
                    latency_ms=0,
                    model=FAL_MODEL,
                    error=str(exc),
                    rendered_image=page.image_path,
                )
            )

    if errors == 0:
        status = "success"
    elif errors == len(routed_pages):
        status = "failed"
    else:
        status = "partial"

    return RawExtractionResult(
        document=DocumentTrace(
            filename=path.name,
            sha256=sha256_file(str(path)),
            page_count=count_pages(str(path)),
        ),
        pages=traces,
        status=status,
    )
