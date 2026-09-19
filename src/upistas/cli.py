"""Línea de comandos: `uv run upistas run --lote lote1`."""
import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from upistas.aplicacion.lote import consolidar_lote
from upistas.aplicacion.procesar import leer_documento
from upistas.config import settings


def documentos(args: argparse.Namespace) -> list[Path]:
    carpeta = args.facturas or settings.caja_dir / "facturas"
    pdfs = sorted(carpeta.glob("*.pdf"))[: args.limit or None]
    if not pdfs:
        print(f"No hay PDFs en {carpeta}", file=sys.stderr)
    return pdfs


def guardar_jsonl(filas: list[dict], nombre: str) -> Path:
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    salida = settings.outputs_dir / nombre
    with salida.open("w", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return salida


def cmd_extract(args: argparse.Namespace) -> int:
    from upistas.infra import contenedor

    contenedor.configurar(replace(settings, usar_ocr=args.ocr))
    pdfs = documentos(args)
    if not pdfs:
        return 1
    filas = []
    for ruta in pdfs:
        extraida = leer_documento(ruta, contenedor.lectores())
        filas.append({
            "file_id": ruta.name,
            "extraccion": extraida.model_dump(mode="json") if extraida else None,
            "errores": extraida.errores or [] if extraida else ["No se pudo extraer el documento"],
        })
    salida = guardar_jsonl(filas, args.salida)
    print(f"{len(filas)} documentos extraídos sin clasificar -> {salida}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from upistas.infra import contenedor

    contenedor.configurar(replace(
        settings,
        excel_path=args.excel or settings.excel_path,
        erp_snapshot=args.erp_snapshot or settings.erp_snapshot,
        erp_url=getattr(args, "erp_url", None) or settings.erp_url,
        usar_erp_http=bool(getattr(args, "erp_url", None)),
        usar_ocr=args.ocr,
    ))
    pdfs = documentos(args)
    if not pdfs:
        return 1
    print("Cargando Excel y referencias del ERP...", flush=True)
    try:
        refs = contenedor.referencias()
    except (OSError, ValueError, KeyError) as exc:
        print(f"No se pudieron cargar las fuentes: {exc}", file=sys.stderr)
        return 2
    if not refs.proveedores or not refs.asientos:
        if not refs.proveedores:
            print("Falta el maestro de proveedores: indica --excel.", file=sys.stderr)
        if not refs.asientos:
            print("Faltan datos del ERP: arranca el bridge o indica --erp-snapshot.", file=sys.stderr)
        print("No se han generado decisiones. Para comprobar solo la lectura usa: upistas extract --facturas <carpeta>", file=sys.stderr)
        return 2

    from upistas.infra import pipeline

    print(f"Excel: {len(refs.proveedores)} proveedores | ERP: {len(refs.asientos)} asientos", flush=True)
    print(f"Procesando {len(pdfs)} PDF | OCR {'activado' if args.ocr else 'desactivado'}", flush=True)
    pipeline.iniciar()
    t0 = time.perf_counter()
    handles = pipeline.encolar_lote(pdfs, args.lote, args.norma)
    individuales = []
    for indice, handle in enumerate(handles, 1):
        individuales.append(handle.get_result())
        if indice % 25 == 0 or indice == len(handles):
            print(f"Procesadas: {indice}/{len(handles)}", flush=True)
    resultados = consolidar_lote(individuales)
    dt = time.perf_counter() - t0

    print("\nRESULTADOS", flush=True)
    for indice, (ruta, resultado) in enumerate(zip(pdfs, resultados), 1):
        print("\n" + "=" * 72)
        print(f"[{indice:03d}/{len(resultados):03d}] {resultado['file_id']}")
        print("\nTEXTO EXTRAIDO:")
        print(contenedor.texto_extraido(ruta) or "(No se pudo recuperar texto)")
        print(f"\nRESULTADO: {resultado['result']}")
        print(f"MOTIVO: {resultado['motivo']}", flush=True)
    resumen = Counter(r["result"] for r in resultados)
    print("\nRESUMEN")
    for estado in ("PAGAR", "NO_PAGAR", "ESCALAR"):
        print(f"  {estado}: {resumen[estado]}")
    print(f"{len(resultados)} facturas en {dt:.1f}s")
    if args.salida:
        salida = guardar_jsonl(resultados, args.salida)
        print(f"Informe guardado en {salida}")
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    p = argparse.ArgumentParser(prog="upistas")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Procesa las facturas de La Caja")
    run.add_argument("--lote", default="lote1")
    run.add_argument("--facturas", type=Path, help="Carpeta de PDFs; por defecto CAJA_DIR/facturas")
    run.add_argument("--excel", type=Path, help="Maestro con hojas Proveedores y Pedidos_2026")
    run.add_argument("--erp-snapshot", type=Path, help="JSON: lista de asientos con id, pedido, proveedor_id, nif, importe decimal, fecha y estado")
    run.add_argument("--erp-url", default=settings.erp_url, help="URL del bridge HTTP; por defecto ERP_URL o http://127.0.0.1:8009")
    run.add_argument("--ocr", action="store_true", help="Habilita Fal GOT-OCR para escaneos; requiere FAL_KEY y el extra ocr")
    run.add_argument("--norma", default="v3")
    run.add_argument("--salida", help="Opcional: guardar además un informe JSONL en outputs")
    run.add_argument("--limit", type=int, default=0, help="Procesar solo las N primeras (pruebas)")
    run.set_defaults(func=cmd_run)
    extract = sub.add_parser("extract", help="Extrae campos sin Excel, ERP ni decisiones de pago")
    extract.add_argument("--facturas", type=Path, help="Carpeta de PDFs; por defecto CAJA_DIR/facturas")
    extract.add_argument("--ocr", action="store_true", help="Habilita OCR de pago con Fal; requiere FAL_KEY y el extra ocr")
    extract.add_argument("--limit", type=int, default=0)
    extract.add_argument("--salida", default="extraidas.jsonl")
    extract.set_defaults(func=cmd_extract)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
