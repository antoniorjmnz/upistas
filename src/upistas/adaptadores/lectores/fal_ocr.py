from pathlib import Path
from tempfile import TemporaryDirectory

from upistas.puertos import LecturaFallida


class FalOCR:
    def __call__(self, imagen: bytes) -> str:
        try:
            import fal_client
        except ImportError as exc:
            raise LecturaFallida("OCR requiere instalar el extra: uv sync --extra ocr") from exc

        with TemporaryDirectory(prefix="upistas-ocr-") as carpeta:
            ruta = Path(carpeta) / "pagina.png"
            ruta.write_bytes(imagen)
            url = fal_client.upload_file(str(ruta))
            respuesta = fal_client.subscribe(
                "fal-ai/got-ocr/v2",
                arguments={"input_image_urls": [url], "do_format": False, "multi_page": False},
                with_logs=False,
            )
        textos = respuesta.get("outputs")
        if not isinstance(textos, list) or not textos or not all(isinstance(t, str) for t in textos):
            raise LecturaFallida("Respuesta OCR sin outputs de texto")
        texto = "\n".join(textos)
        if not texto.strip():
            raise LecturaFallida("OCR sin texto")
        return texto
