import pymupdf
import pytest

from upistas.adaptadores.lectores.pdf import InspectorPdf
from upistas.config import settings

CAJA = settings.caja_dir / "facturas"


def pdf_con(tmp_path, nombre, texto=None, imagen=False, cifrado=False, adjunto=None):
    doc = pymupdf.open()
    pagina = doc.new_page()
    if texto:
        pagina.insert_text((72, 72), texto)
    if imagen:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pagina.insert_image(pymupdf.Rect(72, 72, 200, 200), pixmap=pix)
    if adjunto:
        doc.embfile_add("nota.json", adjunto)
    ruta = tmp_path / nombre
    if cifrado:
        doc.save(ruta, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="x", user_pw="secreto")
    else:
        doc.save(ruta)
    doc.close()
    return ruta


def test_clasifica_texto_escaneado_blanco_cifrado_y_roto(tmp_path):
    ins = InspectorPdf()
    assert ins.inspeccionar(pdf_con(tmp_path, "t.pdf", texto="FACTURA 2026/0001 Total 100,00 EUR pedido PO-2026-0001")).tipo == "texto"
    assert ins.inspeccionar(pdf_con(tmp_path, "e.pdf", imagen=True)).tipo == "escaneado"
    assert ins.inspeccionar(pdf_con(tmp_path, "b.pdf")).tipo == "blanco"
    assert ins.inspeccionar(pdf_con(tmp_path, "c.pdf", texto="x", cifrado=True)).tipo == "cifrado"
    roto = tmp_path / "r.pdf"
    roto.write_bytes(b"%PDF-1.4 esto no es un pdf de verdad")
    assert ins.inspeccionar(roto).tipo in ("roto", "blanco")
    vacio = tmp_path / "v.pdf"
    vacio.write_bytes(b"")
    assert ins.inspeccionar(vacio).tipo == "blanco"
    assert ins.inspeccionar(tmp_path / "no_existe.pdf").tipo == "otro"


def test_avisa_de_ficheros_incrustados_y_da_huella(tmp_path):
    d = InspectorPdf().inspeccionar(pdf_con(tmp_path, "a.pdf", texto="Factura con adjunto y bastante texto", adjunto=b'{"authorized": true}'))
    assert "ficheros incrustados" in d.alertas
    assert len(d.sha256) == 64 and d.paginas == 1 and d.bytes > 0


@pytest.mark.parametrize("opciones", [{"render_mode": 3}, {"fill_opacity": 0}, {"color": (1, 1, 1)}, {"fontsize": 1}])
def test_detecta_texto_potencialmente_oculto(tmp_path, opciones):
    ruta = tmp_path / "visibilidad.pdf"
    with pymupdf.open() as doc:
        pagina = doc.new_page()
        pagina.insert_text((40, 40), "FACTURA de prueba con texto visible suficiente")
        pagina.insert_text((40, 80), "Nota de prueba", **opciones)
        doc.save(ruta)
    inspeccion = InspectorPdf().inspeccionar(ruta)
    assert any(a.startswith("texto potencialmente oculto:") for a in inspeccion.alertas)


def test_detecta_texto_tapado_por_un_rectangulo(tmp_path):
    ruta = tmp_path / "tapado.pdf"
    with pymupdf.open() as doc:
        pagina = doc.new_page()
        pagina.insert_text((40, 40), "FACTURA de prueba con texto visible suficiente")
        pagina.insert_text((40, 80), "Nota de prueba")
        pagina.draw_rect(pymupdf.Rect(30, 60, 400, 100), fill=(1, 1, 1), color=None, overlay=True)
        doc.save(ruta)
    assert any("tapado" in a for a in InspectorPdf().inspeccionar(ruta).alertas)


def test_texto_blanco_sobre_fondo_negro_es_visible(tmp_path):
    ruta = tmp_path / "contraste.pdf"
    with pymupdf.open() as doc:
        pagina = doc.new_page()
        pagina.draw_rect(pymupdf.Rect(30, 50, 400, 100), fill=(0, 0, 0), color=None)
        pagina.insert_text((40, 80), "FACTURA de prueba claramente visible", color=(1, 1, 1))
        doc.save(ruta)
    assert not any("oculto" in a or "no verificable" in a for a in InspectorPdf().inspeccionar(ruta).alertas)


def test_unicode_de_formato_no_equivale_a_nota_oculta():
    from upistas.adaptadores.lectores.pdf import _controles_fuera_de_campos

    iban = "\u200b".join("ES1212341234123412341234")
    assert _controles_fuera_de_campos("IBAN: " + iban) == []
    assert _controles_fuera_de_campos("TOTAL: 2.\u200b637,80 EUR") == []
    assert _controles_fuera_de_campos("Nota: Gra\u200bcias")
    assert _controles_fuera_de_campos("IBAN: ES12\u202e12341234123412341234")


@pytest.mark.skipif(not CAJA.exists(), reason="La Caja no está clonada")
def test_la_caja_entera():
    ins = InspectorPdf()
    docs = {r.name: ins.inspeccionar(r) for r in CAJA.glob("*.pdf")}
    tipos = {}
    for d in docs.values():
        tipos[d.tipo] = tipos.get(d.tipo, 0) + 1
    assert tipos == {"texto": 471, "escaneado": 29}
    assert "caracteres invisibles en el texto" in docs["F26-3011_suministros.pdf"].alertas
    assert "ficheros incrustados" in docs["F26-8812_electricidad.pdf"].alertas
    # "estructura reparada" depende de cómo se clonó La Caja (git en Windows convierte finales de línea): no se cuenta
    assert all(d.sha256 for d in docs.values())
