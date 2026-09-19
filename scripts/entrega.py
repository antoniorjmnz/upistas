"""Monta la carpeta de entrega: un repo aparte con solo outcomes.jsonl, outcomes_lote2.jsonl y albertitos_plan.pdf.

    uv run python scripts/entrega.py                    # verifica y copia a ../la-caja-outcomes
    uv run python scripts/entrega.py --destino /ruta    # a otra carpeta
    uv run python scripts/entrega.py --git              # y además crea el repo aparte con un commit local (nunca push)

Antes de copiar comprueba cada outcomes contra la carpeta de La Caja que le toca (facturas/ para el
lote 1, facturas_primin/ para el lote 2): una línea JSON por fichero, ni una más ni una menos, result
válido, sin file_id repetidos y UTF-8 sin BOM. Si algo falla no copia nada y sale con error.
scripts/check.py usa esta misma comprobación.
"""
import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTADOS = ("PAGAR", "NO_PAGAR", "ESCALAR")
# Fichero de la entrega → carpeta de La Caja con la que tiene que cuadrar.
OUTCOMES = {"outcomes.jsonl": "facturas", "outcomes_lote2.jsonl": "facturas_primin"}
PLAN = "albertitos_plan.pdf"
FICHEROS = (*OUTCOMES, PLAN)
BOM = b"\xef\xbb\xbf"


def ficheros_de(carpeta: Path) -> set[str] | None:
    """Nombres de los ficheros de una carpeta de La Caja; None si la carpeta no existe."""
    return {p.name for p in carpeta.iterdir() if p.is_file()} if carpeta.is_dir() else None


def verificar_outcomes(ruta: Path, esperados: set[str] | None) -> tuple[list[str], Counter]:
    """Problemas del fichero (ninguno si está bien) y cuántas facturas van a cada resultado.

    `esperados` son los nombres de los ficheros de la carpeta de La Caja; None si no se puede comprobar.
    """
    problemas: list[str] = []
    conteo: Counter = Counter()
    datos = ruta.read_bytes()
    if datos.startswith(BOM):
        problemas.append("empieza con BOM: tiene que ser UTF-8 sin BOM")
        datos = datos[len(BOM):]
    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"no es UTF-8 válido (byte {exc.start})"], conteo
    vistos: set[str] = set()
    for n, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        try:
            fila = json.loads(linea)
        except json.JSONDecodeError:
            problemas.append(f"línea {n}: no es JSON")
            continue
        if not isinstance(fila, dict):
            problemas.append(f"línea {n}: no es un objeto JSON")
            continue
        file_id, resultado = fila.get("file_id"), fila.get("result")
        if not isinstance(file_id, str) or not file_id:
            problemas.append(f"línea {n}: sin file_id")
            continue
        if resultado in RESULTADOS:
            conteo[resultado] += 1
        else:
            problemas.append(f"línea {n} ({file_id}): result inválido: {resultado!r}")
        if file_id in vistos:
            problemas.append(f"línea {n}: file_id repetido: {file_id}")
        vistos.add(file_id)
    if esperados is not None:
        faltan, sobran = sorted(esperados - vistos), sorted(vistos - esperados)
        if faltan:
            problemas.append(f"faltan {len(faltan)} facturas de La Caja, p. ej. {faltan[:3]}")
        if sobran:
            problemas.append(f"sobran {len(sobran)} file_id que no están en La Caja, p. ej. {sobran[:3]}")
    return problemas, conteo


def _fallo(problemas: list[str]) -> int:
    print("No se puede montar la entrega:")
    for p in problemas:
        print(f"  - {p}")
    return 1


def _git(destino: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=destino, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _commit(destino: Path) -> int:
    """Deja el repo aparte con un commit local. Subirlo es cosa de una persona, nunca de este script."""
    if not (destino / ".git").is_dir():
        r = _git(destino, "init", "-q", "-b", "main")
        if r.returncode:
            return _fallo([f"git init ha fallado: {r.stderr.strip()}"])
    r = _git(destino, "add", "--", *FICHEROS)
    if r.returncode:
        return _fallo([f"git add ha fallado: {r.stderr.strip()}"])
    if _git(destino, "diff", "--cached", "--quiet").returncode == 0:
        print("El repo de entrega ya tenía este contenido; no hay nada nuevo que confirmar.")
        return 0
    r = _git(destino, "commit", "-q", "-m", "Entrega: outcomes de los lotes 1 y 2 y albertitos_plan.pdf")
    if r.returncode:
        return _fallo([f"git commit ha fallado: {(r.stderr or r.stdout).strip()}"])
    print(f"Commit hecho en {destino}. Subirlo a GitHub es cosa tuya (git push); este script no lo hace.")
    return 0


def montar_entrega(outputs: Path, plan: Path, caja: Path, destino: Path, git: bool = False) -> int:
    """Verifica los tres ficheros, los copia a `destino` y, si se pide, deja el repo con un commit local.

    Devuelve el código de salida: 0 si la entrega ha quedado lista, 1 si algo no cuadra (y entonces no copia nada).
    """
    origenes = {nombre: outputs / nombre for nombre in OUTCOMES} | {PLAN: plan}
    faltan = [f"{nombre}: no existe {ruta}" for nombre, ruta in origenes.items() if not ruta.is_file()]
    if faltan:
        return _fallo(faltan)
    problemas, resumen = [], []
    for nombre, carpeta in OUTCOMES.items():
        esperados = ficheros_de(caja / carpeta)
        if esperados is None:
            problemas.append(f"{nombre}: no encuentro {caja / carpeta} para comprobar que está cada factura (revisa CAJA_DIR)")
        fallos, conteo = verificar_outcomes(origenes[nombre], esperados)
        problemas += [f"{nombre}: {p}" for p in fallos]
        reparto = " · ".join(f"{r} {conteo[r]}" for r in RESULTADOS)
        resumen.append(f"{nombre}: {sum(conteo.values())} facturas de {carpeta}/ · {reparto}")
    resumen.append(f"{PLAN}: {plan.stat().st_size / 1024:.0f} KB")
    if problemas:
        return _fallo(problemas)
    destino.mkdir(parents=True, exist_ok=True)
    intrusos = sorted(p.name for p in destino.iterdir() if p.name != ".git" and p.name not in FICHEROS)
    if intrusos:
        return _fallo([f"en {destino} hay cosas que no van en la entrega: {intrusos}. Quítalas a mano; este script no borra nada."])
    for nombre, ruta in origenes.items():
        shutil.copyfile(ruta, destino / nombre)
    print("\n".join(resumen))
    print(f"Entrega lista en {destino}: solo {', '.join(FICHEROS)}")
    return _commit(destino) if git else 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Monta la carpeta de entrega y comprueba que los outcomes cuadran con La Caja.")
    p.add_argument("--destino", type=Path, default=ROOT.parent / "la-caja-outcomes", help="Carpeta del repo aparte (por defecto ../la-caja-outcomes)")
    p.add_argument("--git", action="store_true", help="Crear el repo aparte y hacer un commit local; nunca hace push")
    p.add_argument("--plan", type=Path, default=ROOT / "docs" / PLAN,
                   help="Ruta del albertitos_plan.pdf (vive fuera del repo; por defecto docs/albertitos_plan.pdf)")
    args = p.parse_args(argv)
    from upistas.config import settings  # aquí y no arriba: check.py importa este fichero sin cargar el producto

    return montar_entrega(settings.outputs_dir, args.plan, settings.caja_dir, args.destino, args.git)


if __name__ == "__main__":
    sys.exit(main())
