"""Línea de comandos.

    uv run upistas erp sync        trae el ERP de Alberto a nuestra copia local
    uv run upistas erp estado      última sincronización y versión de los datos
    uv run upistas run             sincroniza el ERP, lee y decide un lote → outputs/outcomes.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

from upistas.config import settings


def _resumen_sync(s) -> str:
    if not s.ok:
        return f"✘ Falló a las {s.fin.astimezone():%H:%M:%S}: {s.error}"
    e = s.estadisticas
    cambios = f" · cambios: {s.nuevos} nuevos, {s.modificados} modificados, {s.eliminados} eliminados" if (s.nuevos or s.modificados or s.eliminados) else ""
    return (
        f"✔ {s.n_asientos} asientos · versión {s.version}{' · lote 2 cargado' if s.lote2_cargado else ''}{cambios}\n"
        f"  {e.peticiones} peticiones en {e.segundos:.1f}s · reintentos ORA-00600: {e.reintentos_ora} · "
        f"esperas 429: {e.esperas_429} · relogins: {e.relogins} · errores de red: {e.errores_red}"
    )


def cmd_erp(args: argparse.Namespace) -> int:
    from upistas.aplicacion.sincronizar_erp import sincronizar_erp
    from upistas.infra import contenedor

    almacen = contenedor.almacen_erp()
    if args.accion == "sync":
        s = sincronizar_erp(contenedor.cliente_erp(), almacen)
        print("ERP:", _resumen_sync(s))
        if s.ok:
            return 0
        anterior = almacen.ultima()
        if anterior:
            print(f"  Sigo con la última copia buena: versión {anterior.version} del {anterior.fin.astimezone():%d/%m %H:%M}")
            return 0
        print(f"  No hay copia anterior. Arranca el ERP (python {settings.caja_dir / 'alberto_erp.py'}) y reintenta.", file=sys.stderr)
        return 1
    ultima, buena = almacen.ultima(solo_correctas=False), almacen.ultima()
    if ultima is None:
        print("Nunca se ha sincronizado. Ejecuta: uv run upistas erp sync")
        return 1
    print("Última sincronización:", _resumen_sync(ultima))
    if buena and buena is not ultima and not ultima.ok:
        print("Copia en uso:", _resumen_sync(buena))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from upistas.infra import pipeline

    carpeta = Path(args.carpeta) if args.carpeta else settings.caja_dir / "facturas"
    rutas = sorted(p for p in carpeta.iterdir() if p.is_file())[: args.limit or None]
    if not rutas:
        print(f"No hay documentos en {carpeta}", file=sys.stderr)
        return 1
    print(f"Lote {args.lote} · norma {args.norma} · {len(rutas)} documentos de {carpeta}")
    pipeline.iniciar()
    try:
        inf = pipeline.procesar_lote(args.lote, rutas, args.norma, sincronizar=not args.sin_sync)
    except RuntimeError as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 1

    if inf.sincronizacion:
        print("ERP:", _resumen_sync(inf.sincronizacion))
    for aviso in inf.avisos:
        print("  ⚠", aviso)
    r = inf.ejecucion.resumen
    n = len(rutas)
    print(f"Datos: ERP {inf.ejecucion.version_erp} · Excel {inf.ejecucion.version_excel} · ejecución #{inf.ejecucion.id}")
    print(f"Lectura: {inf.leidos_ahora} leídos ahora, {inf.desde_cache} ya leídos · {r['leidos']}/{n} legibles · "
          f"{inf.segundos_lectura:.1f}s ({n / max(inf.segundos_lectura, 1e-9):.1f} docs/s) · por método: {r['por_metodo']}")
    if r["tokens_in"] or r["coste_eur"]:
        print(f"  IA: {r['tokens_in']} tokens de entrada, {r['tokens_out']} de salida, {r['coste_eur']:.4f} €")
    print(f"Decisión: PAGAR {r['PAGAR']} · NO_PAGAR {r['NO_PAGAR']} · ESCALAR {r['ESCALAR']} · "
          f"con alertas {r['con_alertas']} · con notas {r['con_notas']} · {inf.segundos_decision:.2f}s")

    settings.outputs_dir.mkdir(exist_ok=True)
    salida = settings.outputs_dir / args.salida
    with salida.open("w", encoding="utf-8") as f:
        for d in inf.decisiones:
            f.write(json.dumps(d.outcome, ensure_ascii=False) + "\n")
    print(f"→ {salida} ({len(inf.decisiones)} líneas)")

    if inf.anterior:
        print(f"Respecto a la ejecución #{inf.anterior.id} ({inf.anterior.inicio.astimezone():%d/%m %H:%M}, datos {inf.anterior.version_datos}): "
              f"{len(inf.cambios)} facturas cambian de resultado")
        for c in inf.cambios[:15]:
            print(f"  {c.file_id}: {c.antes} → {c.despues} ({c.motivo})")
        if len(inf.cambios) > 15:
            print(f"  … y {len(inf.cambios) - 15} más")
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="upistas")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Sincroniza el ERP, lee y decide un lote")
    run.add_argument("--lote", default="lote1")
    run.add_argument("--norma", default="v3")
    run.add_argument("--carpeta", help="Carpeta con los documentos (por defecto ../caja/facturas)")
    run.add_argument("--salida", default="outcomes.jsonl")
    run.add_argument("--limit", type=int, default=0, help="Procesar solo los N primeros (pruebas)")
    run.add_argument("--sin-sync", action="store_true", help="No hablar con el ERP: usar la última copia")
    run.set_defaults(func=cmd_run)

    erp = sub.add_parser("erp", help="Conexión con el ERP de Alberto")
    erp.add_argument("accion", choices=["sync", "estado"])
    erp.set_defaults(func=cmd_erp)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
