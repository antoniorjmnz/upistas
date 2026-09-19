"""Comprobaciones del repo: lo mismo en local (`python scripts/check.py`) y en CI.

Tooling del equipo, independiente del lenguaje del producto.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures = []


def step(name):
    print(f"\n== {name}")


def fail(msg):
    failures.append(msg)
    print(f"  ✘ {msg}")


def ok(msg):
    print(f"  ✔ {msg}")


def check_contracts():
    step("Contratos: los ejemplos cumplen su schema")
    try:
        import jsonschema
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "jsonschema"], check=True
        )
        import jsonschema
    for ex in sorted((ROOT / "contracts/examples").glob("*.json")):
        schema_name = ex.name.split(".")[0] + ".schema.json"
        schema = json.loads(
            (ROOT / "contracts" / schema_name).read_text(encoding="utf-8")
        )
        errors = list(
            jsonschema.Draft202012Validator(schema).iter_errors(
                json.loads(ex.read_text(encoding="utf-8"))
            )
        )
        should_pass = ".ok." in ex.name
        if should_pass and errors:
            fail(f"{ex.name}: {errors[0].message}")
        elif not should_pass and not errors:
            fail(f"{ex.name}: debería fallar y pasa")
        else:
            ok(ex.name)


def check_outcomes():
    step("Outcomes: un resultado válido por archivo")
    sys.path.insert(0, str(ROOT / "scripts"))
    from entrega import OUTCOMES, ficheros_de, verificar_outcomes  # la misma comprobación que la entrega

    caja = Path(os.environ.get("CAJA_DIR", ROOT.parent / "caja"))
    files = sorted((ROOT / "outputs").glob("outcomes*.jsonl"))
    if not files:
        ok("no hay outcomes todavía (se omite)")
        return
    for f in files:
        esperados = ficheros_de(caja / OUTCOMES[f.name]) if f.name in OUTCOMES else None
        problemas, conteo = verificar_outcomes(f, esperados)
        for p in problemas:
            fail(f"{f.name}: {p}")
        if not problemas:
            ok(f"{f.name}: {sum(conteo.values())} outcomes")


def check_hygiene():
    step("Higiene: sin secretos ni datos en git")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    for t in tracked:
        if (
            t == ".env"
            or t.startswith(("data/", "outputs/"))
            and not t.endswith(".gitkeep")
        ):
            fail(f"archivo que no debería estar en git: {t}")
        if t.lower().endswith((".pdf", ".xlsx")):
            fail(f"binario de datos en git: {t}")
    pattern = re.compile(
        r"sk-ant-[A-Za-z0-9_-]{10,}|sk-or-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}"
    )
    for t in tracked:
        p = ROOT / t
        if p.suffix in {".png", ".jpg", ".webp"} or not p.is_file():
            continue
        if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
            fail(f"posible API key en {t}")
    if not failures:
        ok(f"{len(tracked)} archivos revisados")


def check_generated():
    step("Contratos: modelos Pydantic generados al día")
    if not (ROOT / "src/upistas/contracts").exists():
        ok("aún no hay modelos generados (se omite)")
        return
    r = subprocess.run([sys.executable, "scripts/gen_contracts.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    (ok if r.returncode == 0 else fail)(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "gen_contracts --check")


def check_capas():
    step("Arquitectura: nadie cruza las capas")
    if not (ROOT / "pyproject.toml").exists():
        ok("aún no hay proyecto (se omite)")
        return
    exe = Path(sys.executable).parent / ("lint-imports.exe" if os.name == "nt" else "lint-imports")
    r = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        ok("contratos de capas respetados")
    else:
        fail("import prohibido entre capas:\n" + r.stdout[-1500:])


def run_tests():
    step("Tests del proyecto")
    if (ROOT / "pyproject.toml").exists():
        r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
        (ok if r.returncode == 0 else fail)("pytest")
    elif (ROOT / "package.json").exists():
        r = subprocess.run("npm test --silent", cwd=ROOT, shell=True)
        (ok if r.returncode == 0 else fail)("npm test")
    else:
        ok("aún no hay proyecto (se omite)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    check_contracts()
    check_generated()
    check_capas()
    check_outcomes()
    check_hygiene()
    run_tests()
    print(
        "\n"
        + (
            "✘ FALLA: " + str(len(failures)) + " problema(s)"
            if failures
            else "✔ Todo OK"
        )
    )
    sys.exit(1 if failures else 0)
