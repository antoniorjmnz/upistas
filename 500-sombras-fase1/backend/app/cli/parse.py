from __future__ import annotations

import argparse
import json

from app.extraction.pipeline import (
    extract_raw_document,
)

from app.extraction.field_parser import (
    parse_pages,
)


def main():

    parser = argparse.ArgumentParser(
        description="OCR + parser de factura"
    )

    parser.add_argument(
        "pdf",
        help="Ruta al PDF",
    )

    args = parser.parse_args()

    # 1. PDF -> OCR
    raw = extract_raw_document(
        args.pdf
    )

    # 2. Convertimos los objetos Pydantic
    #    a diccionarios normales
    pages = [
        page.model_dump()
        for page in raw.pages
    ]

    # 3. OCR -> campos estructurados
    parsed = parse_pages(
        pages
    )

    result = {
        "document":
            raw.document.model_dump(),

        "raw_status":
            raw.status,

        "fields":
            parsed,
    }

    print()
    print("=" * 80)
    print("PARSED INVOICE")
    print("=" * 80)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()