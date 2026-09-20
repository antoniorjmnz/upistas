"""Con OCR o visión, un NIF sin forma de NIF no se da por leído y la factura queda marcada por_ocr."""
import json
from pathlib import Path

from upistas.aplicacion.mapeo import a_factura
from upistas.contracts.factura_extraida import FacturaExtraida

EJEMPLO = json.loads(Path("contracts/examples/factura_extraida.ok.json").read_text(encoding="utf-8"))


def _extraida(metodo: str, nif: str) -> FacturaExtraida:
    datos = json.loads(json.dumps(EJEMPLO))
    datos["metodo"] = metodo
    datos["campos"]["nif"] = {"valor": nif, "confianza": 1.0, "fuente": f"NIF: {nif}", "pagina": 1}
    return FacturaExtraida.model_validate(datos)


def test_por_ocr_un_nif_sin_forma_de_nif_es_no_leido_y_la_factura_va_marcada():
    f = a_factura(_extraida("ocr_determinista", "898120774"))
    assert f.nif is None and "nif" in f.no_leidos and f.por_ocr


def test_por_texto_el_mismo_valor_se_respeta_y_no_va_marcada():
    f = a_factura(_extraida("texto_determinista", "898120774"))
    assert f.nif == "898120774" and "nif" not in f.no_leidos and not f.por_ocr
