"""Línea de comandos.

    uv run upistas erp sync        trae el ERP de Alberto a nuestra copia local
    uv run upistas erp estado      última sincronización y versión de los datos
    uv run upistas run             sincroniza el ERP y procesa La Caja → outputs/outcomes.jsonl
"""
import argparse
import json
import sys
import time

from upistas.config import settings


def _resumen(s) -> str:
    if not s.ok:
        return f"✘ Falló a las {s.fin.astimezone():%H:%M:%S}: {s.error}"
    e = s.estadisticas
    cambios = f" · cambios: {s.nuevos} nuevos, {s.modificados} modificados, {s.eliminados} eliminados" if (s.nuevos or s.modificados or s.eliminados) else ""
    return (
        f"✔ {s.n_asientos} asientos · versión {s.version}{' · lote 2 cargado' if s.lote2_cargado else ''}{cambios}\n"
        f"  {e.peticiones} peticiones en {e.segundos:.1f}s · reintentos ORA-00600: {e.reintentos_ora} · "
        f"esperas 429: {e.esperas_429} · relogins: {e.relogins} · errores de red: {e.errores_red}"
    )


def _sincronizar() -> bool:
    """True si hay una copia del ERP con la que trabajar (nueva o anterior)."""
    from upistas.aplicacion.sincronizar_erp import sincronizar_erp
    from upistas.infra import contenedor

    s = sincronizar_erp(contenedor.cliente_erp(), contenedor.almacen_erp())
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


def cmd_run(args: argparse.Namespace) -> int:
    from upistas.infra import pipeline

    carpeta = settings.caja_dir / "facturas"
    pdfs = sorted(carpeta.glob("*.pdf"))[: args.limit or None]
    if not pdfs:
        print(f"No hay PDFs en {carpeta}", file=sys.stderr)
        return 1
    if not args.sin_sync and not _sincronizar():
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
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="upistas")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Sincroniza el ERP y procesa las facturas de La Caja")
    run.add_argument("--lote", default="lote1")
    run.add_argument("--norma", default="v3")
    run.add_argument("--salida", default="outcomes.jsonl")
    run.add_argument("--limit", type=int, default=0, help="Procesar solo las N primeras (pruebas)")
    run.add_argument("--sin-sync", action="store_true", help="No hablar con el ERP: usar la última copia")
    run.set_defaults(func=cmd_run)

    erp = sub.add_parser("erp", help="Conexión con el ERP de Alberto")
    erp.add_argument("accion", choices=["sync", "estado"])
    erp.set_defaults(func=cmd_erp)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
