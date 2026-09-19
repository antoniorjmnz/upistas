from __future__ import annotations

import os
import time
from pathlib import Path

import fal_client
from dotenv import load_dotenv


# Carga SIEMPRE backend/.env aunque el módulo se ejecute desde otro cwd.
BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


FAL_MODEL = "fal-ai/got-ocr/v2"


class FalOCRError(RuntimeError):
    pass


def _check_configuration() -> None:
    if not os.getenv("FAL_KEY"):
        raise FalOCRError(
            "No existe FAL_KEY. "
            "Copia backend/.env.example a backend/.env "
            "y añade tu clave de Fal."
        )


def ocr_image(image_path: str) -> dict:
    """
    Ejecuta GOT-OCR2 sobre UNA página.

    Una llamada por página hace más sencilla la trazabilidad:
    sabemos qué modelo/latencia/error corresponde a cada página.
    """

    _check_configuration()

    image = Path(image_path)

    if not image.exists():
        raise FalOCRError(
            f"No existe la imagen renderizada: {image}"
        )

    started = time.perf_counter()

    try:
        print(f"[FAL] Upload: {image}")

        image_url = fal_client.upload_file(
            str(image)
        )

        print("[FAL] GOT-OCR2...")

        result = fal_client.subscribe(
            FAL_MODEL,
            arguments={
                "input_image_urls": [image_url],
                "do_format": False,
                "multi_page": False,
            },
        )

        outputs = result.get("outputs", [])

        if not outputs:
            raise FalOCRError(
                "Fal respondió correctamente pero outputs está vacío."
            )

        text = str(outputs[0])

        return {
            "text": text,
            "model": FAL_MODEL,
            "latency_ms": int(
                (time.perf_counter() - started) * 1000
            ),
        }

    except FalOCRError:
        raise

    except Exception as exc:
        latency_ms = int(
            (time.perf_counter() - started) * 1000
        )

        raise FalOCRError(
            f"Fal OCR falló después de {latency_ms} ms: {exc}"
        ) from exc
