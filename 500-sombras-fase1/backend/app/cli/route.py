from __future__ import annotations

import argparse

from app.extraction.pdf_reader import route_pdf


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Comprueba si cada página usará texto nativo "
            "o Fal OCR. Este comando NO llama a Fal."
        )
    )

    parser.add_argument(
        "pdf",
        help="Ruta al PDF",
    )

    args = parser.parse_args()

    pages = route_pdf(args.pdf)

    for page in pages:
        if page.route == "native_text":
            print(
                f"page={page.page_number} "
                f"route=native_text "
                f"chars={len(page.text or '')}"
            )

        else:
            print(
                f"page={page.page_number} "
                f"route=fal_ocr "
                f"image={page.image_path}"
            )


if __name__ == "__main__":
    main()
