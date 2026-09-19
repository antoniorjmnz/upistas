from __future__ import annotations

import argparse

from app.extraction.pipeline import (
    extract_raw_document,
)


def main():
    parser = argparse.ArgumentParser(
        description="Extrae texto trazable de una factura PDF."
    )

    parser.add_argument(
        "pdf",
        help="Ruta al PDF",
    )

    args = parser.parse_args()

    result = extract_raw_document(
        args.pdf
    )

    print()
    print("=" * 80)
    print("RAW EXTRACTION RESULT")
    print("=" * 80)

    print(
        result.model_dump_json(
            indent=2
        )
    )


if __name__ == "__main__":
    main()
