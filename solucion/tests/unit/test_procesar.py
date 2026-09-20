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
