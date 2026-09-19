from pathlib import Path

from upistas.aplicacion.procesar import leer_documento
from upistas.puertos import DocumentoInspeccionado, LecturaFallida


class InspectorFalso:
    def __init__(self, tipo):
        self.tipo = tipo

    def inspeccionar(self, ruta):
        return DocumentoInspeccionado(Path(ruta).name, str(ruta), "abc", 10, self.tipo, 1, ("hola",), ("estructura reparada al abrir",))


class Lector:
    def __init__(self, nombre, tipos, resultado=None):
        self.nombre, self.tipos, self.resultado = nombre, tipos, resultado

    def acepta(self, doc):
        return doc.tipo in self.tipos

    def leer(self, doc):
        if self.resultado is None:
            raise LecturaFallida(f"{self.nombre} no pudo")
        return self.resultado


def test_prueba_los_lectores_en_orden_y_se_queda_con_el_primero_que_puede():
    lectura = leer_documento(Path("x/f.pdf"), InspectorFalso("texto"), [Lector("barato", {"texto"}), Lector("caro", {"texto"}, "LEIDO")])
    assert lectura.extraida == "LEIDO"
    assert lectura.intentos == (("barato", "barato no pudo"),)


def test_si_ninguno_puede_explica_por_que():
    lectura = leer_documento(Path("x/f.pdf"), InspectorFalso("escaneado"), [Lector("texto", {"texto"}), Lector("vision", {"escaneado"})])
    assert lectura.extraida is None
    assert lectura.motivo_fallo == "vision: vision no pudo"


def test_un_documento_ilegible_no_pasa_por_ningun_lector():
    lectura = leer_documento(Path("x/f.pdf"), InspectorFalso("cifrado"), [Lector("texto", {"texto"}, "LEIDO")])
    assert lectura.extraida is None and lectura.intentos == ()
    assert lectura.motivo_fallo.startswith("documento cifrado")


def test_una_lectura_con_errores_se_escala_aunque_los_campos_cuadren():
    from datetime import date

    from upistas.aplicacion.procesar import Lectura, decidir
    from upistas.config import ROOT
    from upistas.contracts.factura_extraida import FacturaExtraida
    from upistas.dominio.modelos import Referencias, Resultado
    from upistas.dominio.norma import Norma

    extraida = FacturaExtraida.model_validate({
        "file_id": "a.pdf", "metodo": "ocr_determinista", "checks": {},
        "documento": {"sha256": "0" * 64, "tipo": "escaneado", "paginas": 2},
        "campos": {c: {"valor": "PO-2026-0001" if c == "pedido" else None, "confianza": 1} for c in
                   ("nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total")},
        "errores": ["Página 2: OCR sin texto"],
    })
    lectura = Lectura(DocumentoInspeccionado("a.pdf", "a.pdf", "0" * 64, 0, "escaneado", 2), extraida)
    refs = Referencias({}, {}, {}, date(2026, 9, 19))
    d = decidir("a.pdf", lectura, refs, Norma.desde_toml(ROOT / "normas" / "v3.toml"))
    assert d.resultado is Resultado.ESCALAR and "Página 2" in d.motivo and d.pedido == "PO-2026-0001"
