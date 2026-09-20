"""La carpeta de entrega: solo los tres ficheros, y cada outcomes cuadra con su carpeta de La Caja."""
import json
import subprocess

import pytest

from scripts import entrega

BOM = b"\xef\xbb\xbf"


def _jsonl(ruta, filas, prefijo=b""):
    ruta.write_bytes(prefijo + "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas).encode("utf-8"))


@pytest.fixture
def caja(tmp_path):
    """Una Caja de mentira: tres facturas en el lote 1 y dos en el lote 2."""
    for carpeta, cuantas in (("facturas", 3), ("facturas_primin", 2)):
        (tmp_path / "caja" / carpeta).mkdir(parents=True)
        for i in range(cuantas):
            (tmp_path / "caja" / carpeta / f"f{i}.pdf").write_bytes(b"%PDF")
    return tmp_path / "caja"


@pytest.fixture
def lote_bien(tmp_path, caja):
    """outputs/ con los dos outcomes correctos y el PDF del plan. Devuelve (outputs, plan)."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _jsonl(outputs / "outcomes.jsonl", [{"file_id": f"f{i}.pdf", "result": r} for i, r in enumerate(("PAGAR", "NO_PAGAR", "ESCALAR"))])
    _jsonl(outputs / "outcomes_lote2.jsonl", [{"file_id": "f0.pdf", "result": "PAGAR"}, {"file_id": "f1.pdf", "result": "PAGAR"}])
    plan = tmp_path / "docs" / "albertitos_plan.pdf"
    plan.parent.mkdir()
    plan.write_bytes(b"%PDF-1.4 plan")
    return outputs, plan


def test_un_outcomes_correcto_no_tiene_problemas_y_cuenta_los_resultados(lote_bien):
    outputs, _ = lote_bien
    problemas, conteo = entrega.verificar_outcomes(outputs / "outcomes.jsonl", {"f0.pdf", "f1.pdf", "f2.pdf"})
    assert problemas == []
    assert conteo == {"PAGAR": 1, "NO_PAGAR": 1, "ESCALAR": 1}


def test_detecta_facturas_que_faltan_y_file_id_que_sobran(tmp_path):
    ruta = tmp_path / "outcomes.jsonl"
    _jsonl(ruta, [{"file_id": "f0.pdf", "result": "PAGAR"}, {"file_id": "otra.pdf", "result": "PAGAR"}])
    problemas, _ = entrega.verificar_outcomes(ruta, {"f0.pdf", "f1.pdf"})
    assert [p.split(",")[0] for p in problemas] == ["faltan 1 facturas de La Caja", "sobran 1 file_id que no están en La Caja"]
    assert "f1.pdf" in problemas[0] and "otra.pdf" in problemas[1]


def test_detecta_result_invalido_repetidos_y_lineas_rotas(tmp_path):
    ruta = tmp_path / "outcomes.jsonl"
    ruta.write_text('{"file_id": "a.pdf", "result": "PAGAR"}\n{"file_id": "a.pdf", "result": "QUIZAS"}\nesto no es json\n{"result": "PAGAR"}\n[1]\n', encoding="utf-8")
    problemas, conteo = entrega.verificar_outcomes(ruta, None)
    assert problemas == [
        "línea 2 (a.pdf): result inválido: 'QUIZAS'",
        "línea 2: file_id repetido: a.pdf",
        "línea 3: no es JSON",
        "línea 4: sin file_id",
        "línea 5: no es un objeto JSON",
    ]
    assert conteo == {"PAGAR": 1}


def test_detecta_bom_y_ficheros_que_no_son_utf8(tmp_path):
    con_bom = tmp_path / "con_bom.jsonl"
    _jsonl(con_bom, [{"file_id": "a.pdf", "result": "PAGAR"}], prefijo=BOM)
    problemas, conteo = entrega.verificar_outcomes(con_bom, {"a.pdf"})
    assert problemas == ["empieza con BOM: tiene que ser UTF-8 sin BOM"]
    assert conteo == {"PAGAR": 1}
    latin1 = tmp_path / "latin1.jsonl"
    latin1.write_bytes('{"file_id": "papelería.pdf", "result": "PAGAR"}\n'.encode("latin-1"))
    problemas, _ = entrega.verificar_outcomes(latin1, None)
    assert problemas == ["no es UTF-8 válido (byte 20)"]


def test_monta_la_carpeta_con_los_tres_ficheros_y_resume(lote_bien, caja, tmp_path, capsys):
    outputs, plan = lote_bien
    destino = tmp_path / "la-caja-outcomes"
    assert entrega.montar_entrega(outputs, plan, caja, destino) == 0
    assert sorted(p.name for p in destino.iterdir()) == ["albertitos_plan.pdf", "outcomes.jsonl", "outcomes_lote2.jsonl"]
    assert (destino / "outcomes.jsonl").read_bytes() == (outputs / "outcomes.jsonl").read_bytes()
    assert (destino / "albertitos_plan.pdf").read_bytes() == plan.read_bytes()
    salida = capsys.readouterr().out
    assert "outcomes.jsonl: 3 facturas de facturas/ · PAGAR 1 · NO_PAGAR 1 · ESCALAR 1" in salida
    assert "outcomes_lote2.jsonl: 2 facturas de facturas_primin/ · PAGAR 2 · NO_PAGAR 0 · ESCALAR 0" in salida
    assert "Entrega lista" in salida


def test_si_falta_un_fichero_lo_dice_y_no_copia_nada(lote_bien, caja, tmp_path, capsys):
    outputs, plan = lote_bien
    plan.unlink()
    destino = tmp_path / "la-caja-outcomes"
    assert entrega.montar_entrega(outputs, plan, caja, destino) == 1
    assert not destino.exists()
    assert f"albertitos_plan.pdf: no existe {plan}" in capsys.readouterr().out


def test_si_un_outcomes_no_cuadra_con_la_caja_no_copia_nada(lote_bien, caja, tmp_path, capsys):
    outputs, plan = lote_bien
    (caja / "facturas_primin" / "nueva.pdf").write_bytes(b"%PDF")
    destino = tmp_path / "la-caja-outcomes"
    assert entrega.montar_entrega(outputs, plan, caja, destino) == 1
    assert not destino.exists()
    assert "outcomes_lote2.jsonl: faltan 1 facturas de La Caja, p. ej. ['nueva.pdf']" in capsys.readouterr().out


def test_sin_la_caja_no_da_por_buena_la_entrega(lote_bien, tmp_path, capsys):
    outputs, plan = lote_bien
    assert entrega.montar_entrega(outputs, plan, tmp_path / "no_esta", tmp_path / "la-caja-outcomes") == 1
    assert "revisa CAJA_DIR" in capsys.readouterr().out


def test_no_toca_una_carpeta_destino_con_otras_cosas(lote_bien, caja, tmp_path, capsys):
    outputs, plan = lote_bien
    destino = tmp_path / "la-caja-outcomes"
    destino.mkdir()
    (destino / "README.md").write_text("no debería estar", encoding="utf-8")
    assert entrega.montar_entrega(outputs, plan, caja, destino) == 1
    assert sorted(p.name for p in destino.iterdir()) == ["README.md"]
    assert "['README.md']" in capsys.readouterr().out


def test_con_git_crea_el_repo_y_un_commit_local(lote_bien, caja, tmp_path, monkeypatch, capsys):
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(variable, "upistas")
    for variable in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(variable, "upistas@example.com")
    outputs, plan = lote_bien
    destino = tmp_path / "la-caja-outcomes"
    assert entrega.montar_entrega(outputs, plan, caja, destino, git=True) == 0
    assert "Commit hecho" in capsys.readouterr().out
    registro = subprocess.run(["git", "log", "--format=%s"], cwd=destino, capture_output=True, text=True, check=True).stdout
    assert registro.splitlines() == ["Entrega: outcomes de los lotes 1 y 2 y albertitos_plan.pdf"]
    versionados = subprocess.run(["git", "ls-files"], cwd=destino, capture_output=True, text=True, check=True).stdout.split()
    assert sorted(versionados) == ["albertitos_plan.pdf", "outcomes.jsonl", "outcomes_lote2.jsonl"]
    assert subprocess.run(["git", "remote"], cwd=destino, capture_output=True, text=True, check=True).stdout == ""
    assert entrega.montar_entrega(outputs, plan, caja, destino, git=True) == 0
    assert "nada nuevo" in capsys.readouterr().out
