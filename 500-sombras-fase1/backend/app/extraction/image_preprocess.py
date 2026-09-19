from pathlib import Path

from PIL import Image


def preprocess_for_ocr(
    input_path: str,
    output_path: str,
    padding: int = 100,
) -> str:

    image = Image.open(
        input_path
    ).convert("RGB")

    # Detectar contenido no blanco
    grayscale = image.convert("L")

    mask = grayscale.point(
        lambda pixel:
        255 if pixel < 245 else 0
    )

    bbox = mask.getbbox()

    if bbox:
        left, top, right, bottom = bbox

        left = max(
            0,
            left - padding,
        )

        top = max(
            0,
            top - padding,
        )

        right = min(
            image.width,
            right + padding,
        )

        bottom = min(
            image.height,
            bottom + padding,
        )

        image = image.crop(
            (
                left,
                top,
                right,
                bottom,
            )
        )

    output = Path(output_path)

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image.save(
        output,
        format="PNG",
    )

    return str(output)