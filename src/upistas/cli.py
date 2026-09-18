"""Línea de comandos: `uv run upistas run --lote lote1`."""
import argparse
import json
import sys
import time

from upistas.config import settings


def cmd_run(args: argparse.Namespace) -> int:
    from upistas.infra import pipeline

    carpeta = settings.caja_dir / "facturas"
    pdfs = sorted(carpeta.glob("*.pdf"))[: args.limit or None]
    if not pdfs:
        print(f"No hay PDFs en {carpeta}", file=sys.stderr)
        return 1
    pipeline.iniciar()
    t0 = time.perf_counter()
    handles = pipeline.encolar_lote(pdfs, args.lote, args.norma)
    resultados = [h.get_result() for h in handles]
    dt = time.perf_counter() - t0

    settings.outputs_dir.mkdir(exist_ok=True)
    salida = settings.outputs_dir / args.salida
    with salida.open("w", encoding="utf-8") as f:
        for r in resultados:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(resultados)} facturas en {dt:.1f}s ({len(resultados) / dt:.1f}/s) → {salida}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="upistas")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Procesa las facturas de La Caja")
    run.add_argument("--lote", default="lote1")
    run.add_argument("--norma", default="v3")
    run.add_argument("--salida", default="outcomes.jsonl")
    run.add_argument("--limit", type=int, default=0, help="Procesar solo las N primeras (pruebas)")
    run.set_defaults(func=cmd_run)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
