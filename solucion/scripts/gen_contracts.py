"""Genera los modelos Pydantic de src/upistas/contracts/ a partir de contracts/*.schema.json.

Ejecutar tras cambiar un contrato: `uv run python scripts/gen_contracts.py`.
`--check` falla si los modelos generados no están al día (lo usa check.py).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "contracts"
OUT = ROOT / "src" / "upistas" / "contracts"
HEADER = "# Generado por scripts/gen_contracts.py desde contracts/. No editar a mano.\n"


def generate(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").write_text(HEADER, encoding="utf-8")
    for schema in sorted(SRC.glob("*.schema.json")):
        stem = schema.name.removesuffix(".schema.json")
        target = dest / (stem + ".py")
        subprocess.run(
            [
                sys.executable, "-m", "datamodel_code_generator",
                "--input", str(schema),
                "--input-file-type", "jsonschema",
                "--class-name", "".join(w.capitalize() for w in stem.split("_")),
                "--encoding", "utf-8",
                "--formatters", "black", "isort",
                "--output", str(target),
                "--output-model-type", "pydantic_v2.BaseModel",
                "--use-annotated",
                "--use-standard-collections",
                "--use-union-operator",
                "--target-python-version", "3.12",
                "--disable-timestamp",
                "--custom-file-header", HEADER.strip(),
            ],
            check=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )


if __name__ == "__main__":
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            generate(Path(tmp))

            def norm(path: Path) -> str:
                return path.read_text(encoding="utf-8").replace("\r\n", "\n")

            stale = [
                p.name
                for p in Path(tmp).glob("*.py")
                if not (OUT / p.name).exists() or norm(OUT / p.name) != norm(p)
            ]
        if stale:
            print(f"Modelos desactualizados: {stale}. Ejecuta: uv run python scripts/gen_contracts.py")
            sys.exit(1)
        print("Modelos de contratos al día")
    else:
        generate(OUT)
        print(f"Generados en {OUT.relative_to(ROOT)}")
