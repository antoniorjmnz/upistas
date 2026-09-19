"""Los repositorios sobre la base de datos y la memoria de pagos entre lotes."""
import pytest

from upistas.adaptadores.persistencia.django_decisiones import RepositorioDecisionesDjango
from upistas.adaptadores.persistencia.django_lecturas import RepositorioLecturasDjango
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.puertos import DecisionGuardada, RegistroLectura

pytestmark = pytest.mark.django_db


def extraida(file_id):
    campo = lambda v: {"valor": v, "confianza": 1.0}  # noqa: E731
    return FacturaExtraida.model_validate({
        "file_id": file_id, "metodo": "vision_llm", "lector": "vision",
        "documento": {"sha256": "a" * 64, "tipo": "escaneado", "paginas": 1, "alertas": ["caracteres invisibles en el texto"]},
        "campos": {k: campo(v) for k, v in {"nif": "B1", "iban": "ES00", "pedido": "PO-2026-0001", "fecha": "2026-01-08", "base": 1, "iva_pct": 21, "iva": 0.21, "total": 1.21}.items()},
        "checks": {}, "coste": {"tokens_in": 900, "tokens_out": 120, "eur": 0.0, "modelo": "qwen3.6", "segundos": 2.5},
    })


def registro(lote, file_id, ext, sha="a" * 64):
    return RegistroLectura(lote=lote, file_id=file_id, ruta=f"/x/{file_id}", sha256=sha, bytes=99, tipo="escaneado", paginas=1,
                           alertas=("caracteres invisibles en el texto",), extraida=ext, segundos=2.5, tokens_in=900, tokens_out=120, modelo="qwen3.6",
                           version="1")


def test_guarda_y_recupera_una_lectura_con_su_coste():
    repo = RepositorioLecturasDjango()
    repo.guardar(registro("lote1", "scan_001.pdf", extraida("scan_001.pdf")))
    r = repo.por_sha("a" * 64, "1")
    assert r.leida and r.metodo == "vision_llm" and r.tokens_in == 900 and r.alertas == ("caracteres invisibles en el texto",)
    assert r.extraida.campos.total.valor == 1.21 and r.version == "1"
    assert [x.file_id for x in repo.del_lote("lote1")] == ["scan_001.pdf"]


def test_el_mismo_contenido_con_otro_nombre_en_otro_lote_se_reconoce():
    repo = RepositorioLecturasDjango()
    repo.guardar(registro("lote1", "scan_001.pdf", extraida("scan_001.pdf")))
    repo.guardar(registro("lote2", "reenvio.pdf", extraida("reenvio.pdf")))
    assert repo.por_sha("a" * 64, "1") is not None
    assert {x.file_id for x in repo.del_lote("lote2")} == {"reenvio.pdf"}


def test_si_cambian_los_lectores_se_vuelve_a_leer_y_se_conserva_la_lectura_vieja():
    repo = RepositorioLecturasDjango()
    repo.guardar(registro("lote1", "scan_001.pdf", extraida("scan_001.pdf")))
    assert repo.por_sha("a" * 64, "2") is None  # con otra versión de lectores no vale la de antes
    nueva = registro("lote1", "scan_001.pdf", extraida("scan_001.pdf"))
    repo.guardar(RegistroLectura(**{**nueva.__dict__, "version": "2", "segundos": 9.0}))
    assert repo.por_sha("a" * 64, "1").segundos == 2.5 and repo.por_sha("a" * 64, "2").segundos == 9.0
    assert repo.del_lote("lote1", "2")[0].segundos == 9.0 and repo.del_lote("lote1")[0].segundos == 9.0


def test_una_lectura_fallida_tambien_se_guarda_con_el_motivo():
    repo = RepositorioLecturasDjango()
    repo.guardar(RegistroLectura(lote="lote1", file_id="roto.pdf", ruta="/x/roto.pdf", sha256="b" * 64, bytes=5, tipo="roto", paginas=0,
                                 alertas=("no se puede abrir: ValueError",), extraida=None, intentos=()))
    r = repo.del_lote("lote1")[0]
    assert not r.leida and r.metodo == "ninguno" and "no se puede abrir" in r.alertas[0]


def test_ejecuciones_decisiones_y_memoria_de_pagos_entre_lotes():
    lecturas, dec = RepositorioLecturasDjango(), RepositorioDecisionesDjango()
    for lote, fid, sha in (("lote1", "a.pdf", "1" * 64), ("lote1", "b.pdf", "2" * 64), ("lote2", "c.pdf", "3" * 64)):
        lecturas.guardar(registro(lote, fid, extraida(fid), sha))

    e1 = dec.iniciar_ejecucion("lote1", "v3", "erpA", "exA", {"nucleos": 8})
    dec.guardar_decisiones(e1.id, [
        DecisionGuardada("a.pdf", "PAGAR", "ok", "PO-2026-0001", "vision_llm", {"file_id": "a.pdf", "result": "PAGAR"}),
        DecisionGuardada("b.pdf", "ESCALAR", "duda", "PO-2026-0002", "vision_llm", {"file_id": "b.pdf", "result": "ESCALAR"}, alertas=("nota sospechosa",)),
    ])
    e1 = dec.terminar_ejecucion(e1.id, {"PAGAR": 1})
    assert e1.estado == "terminada" and e1.version_datos == "erpA+exA" and e1.fin is not None
    assert {d.file_id: d.resultado for d in dec.decisiones(e1.id)} == {"a.pdf": "PAGAR", "b.pdf": "ESCALAR"}

    # La memoria: lo aprobado en lote1 cuenta para lote2, pero no para volver a pasar lote1.
    assert dec.pedidos_aprobados(excepto_lote="lote2") == {"PO-2026-0001"}
    assert dec.pedidos_aprobados(excepto_lote="lote1") == frozenset()

    # Si Alberto aprueba a mano la escalada, también cuenta.
    from web.panel.models import Decision, RevisionHumana

    escalada = Decision.objects.get(documento__file_id="b.pdf")
    RevisionHumana.objects.create(documento=escalada.documento, decision=escalada, quien="alberto", resultado="PAGAR")
    assert dec.pedidos_aprobados(excepto_lote="lote2") == {"PO-2026-0001", "PO-2026-0002"}

    # Volver a pasar el lote sustituye sus decisiones y la lista de ejecuciones va de nueva a vieja.
    e2 = dec.iniciar_ejecucion("lote1", "v3", "erpB", "exA", {})
    dec.guardar_decisiones(e2.id, [DecisionGuardada("a.pdf", "NO_PAGAR", "ya pagado", "PO-2026-0001", "vision_llm", {})])
    dec.terminar_ejecucion(e2.id, {})
    assert [e.id for e in dec.ejecuciones("lote1")] == [e2.id, e1.id]
    assert dec.pedidos_aprobados(excepto_lote="lote2") == {"PO-2026-0002"}  # la última ejecución de lote1 ya no paga PO-0001
