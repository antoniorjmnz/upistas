"""Subir facturas desde la web: dónde se guardan, cómo se lanza el repaso y qué se ve mientras."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from web.panel import almacen, repasos

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
OTRO_PDF = b"%PDF-1.4\n2 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


def _subida(nombre: str, datos: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(nombre, datos, content_type="application/pdf")


def _repaso(**cambios) -> dict:
    """Un repaso montado a mano: el avance vive en memoria, no en la base de datos."""
    return {
        "estado": "en_marcha", "leidos": 0, "total": 0, "lote": "lote1", "ejecucion_id": None,
        "resumen": {}, "error": "", "empezado": timezone.now(), "terminado": None,
    } | cambios


@pytest.fixture(autouse=True)
def sin_repasos_previos():
    repasos._repasos.clear()
    repasos._hilos.clear()
    repasos._dbos_en_marcha = False
    yield
    repasos._repasos.clear()
    repasos._hilos.clear()


# --- El almacén ------------------------------------------------------------------------------


def test_el_almacen_guarda_por_huella_y_no_duplica(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        primera = almacen.guardar("lote1", [_subida("enero.pdf", PDF)])
        otra_vez = almacen.guardar("lote1", [_subida("enero_copia.pdf", PDF)])

    ruta = primera.facturas[0].ruta
    assert ruta == tmp_path / "lotes" / "lote1" / "enero.pdf" and ruta.read_bytes() == PDF  # el pipeline ve el nombre de siempre
    huella = tmp_path / "facturas" / (hashlib.sha256(PDF).hexdigest() + ".pdf")
    assert list((tmp_path / "facturas").iterdir()) == [huella]  # el contenido, una sola vez
    assert otra_vez.facturas[0].ruta == tmp_path / "lotes" / "lote1" / "enero_copia.pdf"
    assert [f.file_id for f in primera.facturas] == ["enero.pdf"]
    assert [f.file_id for f in otra_vez.facturas] == ["enero_copia.pdf"]
    assert not primera.errores and not otra_vez.errores


def test_dos_facturas_distintas_con_el_mismo_nombre_no_chocan(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        guardado = almacen.guardar("lote1", [_subida("factura.pdf", PDF), _subida("factura.pdf", OTRO_PDF)])

    assert [f.file_id for f in guardado.facturas] == ["factura.pdf", "factura-2.pdf"]
    assert len({f.ruta for f in guardado.facturas}) == 2


def test_el_almacen_rechaza_lo_que_no_es_un_pdf(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        guardado = almacen.guardar("lote1", [SimpleUploadedFile("notas.txt", b"hola", content_type="text/plain")])

    assert guardado.facturas == []
    assert guardado.errores == ["«notas.txt» no es un PDF: no se ha guardado."]
    assert list((tmp_path / "facturas").iterdir()) == []


def test_el_almacen_saca_los_pdf_de_un_zip(tmp_path):
    paquete = io.BytesIO()
    with zipfile.ZipFile(paquete, "w") as zip_:
        zip_.writestr("facturas/enero.pdf", PDF)
        zip_.writestr("../fuera/febrero.pdf", OTRO_PDF)  # nada de rutas raras: solo el nombre
        zip_.writestr("lista.txt", b"no es una factura")
    with override_settings(MEDIA_ROOT=tmp_path):
        guardado = almacen.guardar("lote1", [SimpleUploadedFile("facturas.zip", paquete.getvalue())])

    assert sorted(f.file_id for f in guardado.facturas) == ["enero.pdf", "febrero.pdf"]
    assert {f.ruta.parent for f in guardado.facturas} == {tmp_path / "lotes" / "lote1"}
    assert not guardado.errores


# --- Subir y repasar desde la web -------------------------------------------------------------


def test_subir_guarda_los_ficheros_y_lanza_el_repaso(alberto, tmp_path, monkeypatch):
    lanzados = []
    monkeypatch.setattr(repasos, "lanzar", lambda lote, rutas_nuevas=(): lanzados.append((lote, list(rutas_nuevas))) or 7)

    with override_settings(MEDIA_ROOT=tmp_path):
        respuesta = alberto.post(reverse("panel:subir"), {
            "lote": "__nuevo__", "lote_nuevo": "lote9",
            "facturas": [_subida("enero.pdf", PDF), _subida("febrero.pdf", OTRO_PDF)],
        })

    assert respuesta.status_code == 303
    assert respuesta["Location"] == reverse("panel:subir") + "?repaso=7"
    lote, rutas = lanzados[0]
    assert lote == "lote9" and len(rutas) == 2 and all(r.is_file() for r in rutas)


def test_la_pantalla_de_subir_ensena_el_progreso_del_repaso(alberto):
    repasos._repasos[1] = _repaso(leidos=37, total=503)
    html = alberto.get(reverse("panel:subir") + "?repaso=1").content.decode()
    assert "Suelte aquí los PDF" in html and 'name="facturas"' in html
    assert "Leyendo 37 de 503" in html and 'hx-get="' + reverse("panel:repaso_estado", args=[1]) + '"' in html


def test_el_estado_va_contando_lo_leido(alberto):
    repasos._repasos[1] = _repaso(leidos=37, total=503)
    html = alberto.get(reverse("panel:repaso_estado", args=[1])).content.decode()
    assert 'hx-trigger="load, every 1s"' in html and 'hx-swap="outerHTML"' in html
    assert '<i style="width: 7%">' in html and "Leyendo 37 de 503" in html

    repasos._repasos[1] = _repaso(leidos=503, total=503)
    assert "Decidiendo…" in alberto.get(reverse("panel:repaso_estado", args=[1])).content.decode()


def test_el_estado_cuenta_el_resultado_y_deja_de_preguntar(alberto):
    repasos._repasos[1] = _repaso(
        estado="terminado", leidos=5, total=5, ejecucion_id=3,
        resumen={"documentos": 5, "PAGAR": 2, "NO_PAGAR": 1, "ESCALAR": 2}, terminado=timezone.now(),
    )
    html = alberto.get(reverse("panel:repaso_estado", args=[1])).content.decode()
    assert "hx-trigger" not in html and "hx-get" not in html
    assert "De las <b>5</b> facturas del lote 1" in html
    assert "Ver Hoy" in html and "Ir a revisar" in html and reverse("panel:cola") in html


def test_el_estado_dice_si_el_repaso_se_tuerce(alberto):
    repasos._repasos[1] = _repaso(estado="error", error="No hay ninguna copia del ERP")
    html = alberto.get(reverse("panel:repaso_estado", args=[1])).content.decode()
    assert 'class="aviso mal"' in html and "No hay ninguna copia del ERP" in html
    assert "hx-trigger" not in html


def test_un_repaso_que_no_existe_no_esta(alberto):
    assert alberto.get(reverse("panel:repaso_estado", args=[999])).status_code == 404


def test_repasar_lanza_el_lote_actual_y_lleva_al_progreso(alberto, lote_de_prueba, monkeypatch):
    lanzados = []
    monkeypatch.setattr(repasos, "lanzar", lambda lote, rutas_nuevas=(): lanzados.append(lote) or 4)

    respuesta = alberto.post(reverse("panel:repasar"))

    assert respuesta.status_code == 303 and respuesta["Location"] == reverse("panel:subir") + "?repaso=4"
    assert lanzados == ["lote1"]


def test_solo_hay_un_repaso_a_la_vez(lote_de_prueba):
    repasos._repasos[9] = _repaso()
    assert repasos.lanzar("lote1") == 9  # el que ya estaba, sin arrancar otro
    assert repasos._hilos == {}


# --- El hilo de verdad (con el pipeline sustituido) --------------------------------------------


class _EjecucionFalsa:
    id = 42
    resumen = {"documentos": 6, "PAGAR": 4, "NO_PAGAR": 1, "ESCALAR": 1}


class _InformeFalso:
    ejecucion = _EjecucionFalsa()


def test_el_hilo_repasa_todo_el_lote_y_guarda_el_avance(lote_de_prueba, monkeypatch):
    from upistas.infra import pipeline

    arrancado, llamadas = [], []

    def procesar_lote(lote, rutas, version_norma, sincronizar=True, progreso=None):
        llamadas.append((lote, list(rutas), version_norma, sincronizar))
        progreso(1, 6)
        progreso(6, 6)
        return _InformeFalso()

    monkeypatch.setattr(pipeline, "iniciar", lambda: arrancado.append(1))
    monkeypatch.setattr(pipeline, "procesar_lote", procesar_lote)

    id = repasos.lanzar("lote1", [Path("almacen/facturas/nueva.pdf")])
    repasos._hilos[id].join(timeout=10)

    estado = repasos.estado(id)
    assert estado["estado"] == "terminado" and estado["leidos"] == 6 and estado["total"] == 6
    assert estado["ejecucion_id"] == 42 and estado["resumen"]["PAGAR"] == 4 and estado["terminado"] is not None
    assert arrancado == [1]  # DBOS arranca una sola vez, dentro del proceso de la web
    lote, rutas, norma, sincronizar = llamadas[0]
    assert (lote, norma, sincronizar) == ("lote1", "v3", True)
    assert Path("almacen/facturas/nueva.pdf") in rutas and len(rutas) == 6  # las 5 que ya tenía el lote más la nueva


def test_el_hilo_apunta_el_fallo_sin_tirar_la_web(lote_de_prueba, monkeypatch):
    from upistas.infra import pipeline

    def revienta(*args, **kwargs):
        raise RuntimeError("No hay ninguna copia del ERP")

    monkeypatch.setattr(pipeline, "iniciar", lambda: None)
    monkeypatch.setattr(pipeline, "procesar_lote", revienta)

    id = repasos.lanzar("lote1")
    repasos._hilos[id].join(timeout=10)

    estado = repasos.estado(id)
    assert estado["estado"] == "error" and estado["error"] == "No hay ninguna copia del ERP"
    assert estado["terminado"] is not None
