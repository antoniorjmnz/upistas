"""Línea de comandos.

    uv run upistas erp sync        trae el ERP de Alberto a nuestra copia local
    uv run upistas erp estado      última sincronización y versión de los datos
    uv run upistas run             sincroniza el ERP y procesa La Caja → outputs/outcomes.jsonl
"""
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


def _resumen(s) -> str:
    if not s.ok:
        return f"ERROR a las {s.fin.astimezone():%H:%M:%S}: {s.error}"
    e = s.estadisticas
    cambios = f" · cambios: {s.nuevos} nuevos, {s.modificados} modificados, {s.eliminados} eliminados" if (s.nuevos or s.modificados or s.eliminados) else ""
    return (
        f"OK: {s.n_asientos} asientos · versión {s.version}{' · lote 2 cargado' if s.lote2_cargado else ''}{cambios}\n"
        f"  {e.peticiones} peticiones en {e.segundos:.1f}s · reintentos ORA-00600: {e.reintentos_ora} · "
        f"esperas 429: {e.esperas_429} · relogins: {e.relogins} · errores de red: {e.errores_red}"
    )


def _sincronizar() -> bool:
    """True si hay una copia del ERP con la que trabajar (nueva o anterior)."""
    from upistas.aplicacion.sincronizar_erp import sincronizar_erp
    from upistas.infra import contenedor

    s = sincronizar_erp(contenedor.cliente_erp(), contenedor.almacen_erp())
    contenedor.erp.cache_clear()
    contenedor.referencias.cache_clear()
    print("ERP:", _resumen(s))
    if s.ok:
        return True
    anterior = contenedor.almacen_erp().ultima()
    if anterior:
        print(f"  Sigo con la última copia buena: versión {anterior.version} del {anterior.fin.astimezone():%d/%m %H:%M}")
        return True
    print(f"  No hay copia anterior. Arranca el ERP (make erp en {settings.caja_dir}) y reintenta.", file=sys.stderr)
    return False


def cmd_erp(args: argparse.Namespace) -> int:
    from upistas.infra import contenedor

    if args.accion == "sync":
        return 0 if _sincronizar() else 1
    ultima = contenedor.almacen_erp().ultima(solo_correctas=False)
    buena = contenedor.almacen_erp().ultima()
    if ultima is None:
        print("Nunca se ha sincronizado. Ejecuta: uv run upistas erp sync")
        return 1
    print("Última sincronización:", _resumen(ultima))
    if buena and buena is not ultima and not ultima.ok:
        print("Copia en uso:", _resumen(buena))
    return 0


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
        lectura = leer_documento(ruta, contenedor.inspector(), contenedor.lectores())
        extraida = lectura.extraida
        filas.append({
            "file_id": ruta.name,
            "extraccion": extraida.model_dump(mode="json") if extraida else None,
            "errores": extraida.errores or [] if extraida else [lectura.motivo_fallo],
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
    if contenedor.settings.usar_erp_http and contenedor.settings.erp_snapshot is None and not getattr(args, "sin_sync", False):
        if not _sincronizar():
            return 1
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
        if resultado.get("alertas"):
            print("ALERTAS: " + "; ".join(resultado["alertas"]), flush=True)
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

    run = sub.add_parser("run", help="Sincroniza el ERP y procesa las facturas de La Caja")
    run.add_argument("--lote", default="lote1")
    run.add_argument("--facturas", type=Path, help="Carpeta de PDFs; por defecto CAJA_DIR/facturas")
    run.add_argument("--excel", type=Path, help="Maestro con hojas Proveedores y Pedidos_2026")
    run.add_argument("--erp-snapshot", type=Path, help="JSON: lista de asientos con id, pedido, proveedor_id, nif, importe decimal, fecha y estado")
    run.add_argument("--erp-url", default=settings.erp_url, help="URL del bridge HTTP; por defecto ERP_URL o http://127.0.0.1:8009")
    run.add_argument("--ocr", action="store_true", help="Habilita Fal GOT-OCR para escaneos; requiere FAL_KEY y el extra ocr")
    run.add_argument("--norma", default="v3")
    run.add_argument("--salida", help="Opcional: guardar además un informe JSONL en outputs")
    run.add_argument("--limit", type=int, default=0, help="Procesar solo las N primeras (pruebas)")
    run.add_argument("--sin-sync", action="store_true", help="No hablar con el ERP: usar la última copia")
    run.set_defaults(func=cmd_run)
    extract = sub.add_parser("extract", help="Extrae campos sin Excel, ERP ni decisiones de pago")
    extract.add_argument("--facturas", type=Path, help="Carpeta de PDFs; por defecto CAJA_DIR/facturas")
    extract.add_argument("--ocr", action="store_true", help="Habilita OCR de pago con Fal; requiere FAL_KEY y el extra ocr")
    extract.add_argument("--limit", type=int, default=0)
    extract.add_argument("--salida", default="extraidas.jsonl")
    extract.set_defaults(func=cmd_extract)

    erp = sub.add_parser("erp", help="Conexión con el ERP de Alberto")
    erp.add_argument("accion", choices=["sync", "estado"])
    erp.set_defaults(func=cmd_erp)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
