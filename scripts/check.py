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
RESULTS = {"PAGAR", "NO_PAGAR", "ESCALAR"}
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
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "jsonschema"], check=True)
        import jsonschema
    for ex in sorted((ROOT / "contracts/examples").glob("*.json")):
        schema_name = ex.name.split(".")[0] + ".schema.json"
        schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(json.loads(ex.read_text(encoding="utf-8"))))
        should_pass = ".ok." in ex.name
        if should_pass and errors:
            fail(f"{ex.name}: {errors[0].message}")
        elif not should_pass and not errors:
            fail(f"{ex.name}: debería fallar y pasa")
        else:
            ok(ex.name)


def check_outcomes():
    step("Outcomes: un resultado válido por archivo")
    caja = Path(os.environ.get("CAJA_DIR", ROOT.parent / "caja")) / "facturas"
    expected = {p.name for p in caja.glob("*.pdf")} if caja.is_dir() else None
    files = sorted((ROOT / "outputs").glob("outcomes*.jsonl"))
    if not files:
        ok("no hay outcomes todavía (se omite)")
        return
    for f in files:
        seen, bad = {}, 0
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                fail(f"{f.name}:{n} no es JSON"); bad += 1; continue
            if o.get("result") not in RESULTS:
                fail(f"{f.name}:{n} result inválido: {o.get('result')!r}"); bad += 1
            fid = o.get("file_id")
            if fid in seen:
                fail(f"{f.name}:{n} file_id duplicado: {fid}"); bad += 1
            seen[fid] = o
        if f.name == "outcomes.jsonl" and expected is not None:
            missing, extra = expected - seen.keys(), seen.keys() - expected
            if missing:
                fail(f"{f.name}: faltan {len(missing)} archivos, p.ej. {sorted(missing)[:3]}")
            if extra:
                fail(f"{f.name}: sobran {len(extra)} file_id, p.ej. {sorted(extra)[:3]}")
        if not bad:
            ok(f"{f.name}: {len(seen)} outcomes")


def check_hygiene():
    step("Higiene: sin secretos ni datos en git")
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    for t in tracked:
        if t == ".env" or t.startswith(("data/", "outputs/")) and not t.endswith(".gitkeep"):
            fail(f"archivo que no debería estar en git: {t}")
        if t.lower().endswith((".pdf", ".xlsx")):
            fail(f"binario de datos en git: {t}")
    pattern = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}|sk-or-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}")
    for t in tracked:
        p = ROOT / t
        if p.suffix in {".png", ".jpg", ".webp"} or not p.is_file():
            continue
        if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
            fail(f"posible API key en {t}")
    if not failures:
        ok(f"{len(tracked)} archivos revisados")


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
    check_outcomes()
    check_hygiene()
    run_tests()
    print("\n" + ("✘ FALLA: " + str(len(failures)) + " problema(s)" if failures else "✔ Todo OK"))
    sys.exit(1 if failures else 0)
