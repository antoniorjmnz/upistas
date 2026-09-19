from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)

from .extraction.pipeline import (
    extract_raw_document,
)


app = FastAPI(
    title="500 Sombras de Alberto",
    description=(
        "Fase 1: routing PDF + PyMuPDF + Fal GOT-OCR2 "
        "+ trazabilidad cruda."
    ),
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
    }


@app.post("/api/extract/raw")
def extract_raw(
    file: UploadFile = File(...),
):
    filename = Path(
        file.filename or ""
    ).name

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Falta filename.",
        )

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Solo se admiten PDFs.",
        )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="alberto_"
        )
    )

    pdf_path = temp_dir / filename

    try:
        with pdf_path.open("wb") as destination:
            shutil.copyfileobj(
                file.file,
                destination,
            )

        return extract_raw_document(
            str(pdf_path)
        )

    finally:
        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )
