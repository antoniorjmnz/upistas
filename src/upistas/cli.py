"""Línea de comandos.

    uv run upistas erp sync        trae el ERP de Alberto a nuestra copia local
    uv run upistas erp estado      última sincronización y versión de los datos
    uv run upistas run             sincroniza el ERP, lee y decide un lote → outputs/outcomes.jsonl
"""
import argparse
import json
import sys
import unicodedata
from dataclasses import replace
from pathlib import Path

from upistas.config import settings


def texto_seguro(texto: str) -> str:
    return "".join(f"\\u{ord(c):04x}" if unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" else c for c in texto)


def _resumen_sync(s) -> str:
    if not s.ok:
        return f"ERROR a las {s.fin.astimezone():%H:%M:%S}: {s.error}"
    e = s.estadisticas
    cambios = f" · cambios: {s.nuevos} nuevos, {s.modificados} modificados, {s.eliminados} eliminados" if (s.nuevos or s.modificados or s.eliminados) else ""
    return (
        f"OK: {s.n_asientos} asientos · versión {s.version}{' · lote 2 cargado' if s.lote2_cargado else ''}{cambios}\n"
        f"  {e.peticiones} peticiones en {e.segundos:.1f}s · reintentos ORA-00600: {e.reintentos_ora} · "
        f"esperas 429: {e.esperas_429} · relogins: {e.relogins} · errores de red: {e.errores_red}"
    )


def cmd_erp(args: argparse.Namespace) -> int:
    from upistas.aplicacion.sincronizar_erp import sincronizar_erp
    from upistas.infra import contenedor

    almacen = contenedor.almacen_erp()
    if args.accion == "sync":
        s = sincronizar_erp(contenedor.cliente_erp(), almacen)
        contenedor.referencias.cache_clear()
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


def documentos(args: argparse.Namespace) -> list[Path]:
    carpeta = args.facturas or (Path(args.carpeta) if getattr(args, "carpeta", None) else settings.caja_dir / "facturas")
    candidatas = carpeta.iterdir() if getattr(args, "carpeta", None) and carpeta.is_dir() else carpeta.glob("*.pdf")
    rutas = sorted(p for p in candidatas if p.is_file())[: args.limit or None]
    if not rutas:
        print(f"No hay documentos en {carpeta}", file=sys.stderr)
    return rutas


def guardar_jsonl(filas: list[dict], nombre: str) -> Path:
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    salida = settings.outputs_dir / nombre
    with salida.open("w", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return salida


def cmd_extract(args: argparse.Namespace) -> int:
    from upistas.infra import contenedor, lectura_acotada

    contenedor.configurar(replace(settings, usar_ocr=args.ocr,
                                  lectura_timeout_s=getattr(args, "timeout_lectura", settings.lectura_timeout_s)))
    pdfs = documentos(args)
    if not pdfs:
        return 1
    filas = []
    for ruta in pdfs:
        lectura = lectura_acotada.leer(ruta, contenedor.settings)
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
    from upistas.infra import contenedor, pipeline

    contenedor.configurar(replace(
        settings,
        excel_path=args.excel or settings.excel_path,
        erp_snapshot=args.erp_snapshot or settings.erp_snapshot,
        erp_url=getattr(args, "erp_url", None) or settings.erp_url,
        usar_erp_http=bool(getattr(args, "erp_url", None)),
        usar_ocr=args.ocr,
        lectura_timeout_s=getattr(args, "timeout_lectura", settings.lectura_timeout_s),
    ))
    rutas = documentos(args)
    if not rutas:
        return 1
    try:
        proveedores = contenedor.maestro().proveedores()
    except (OSError, ValueError, KeyError) as exc:
        print(f"No se pudo cargar el Excel: {exc}", file=sys.stderr)
        return 2
    if not proveedores:
        print("Falta el maestro de proveedores: indica --excel. Para comprobar solo la lectura usa upistas extract.", file=sys.stderr)
        return 2

    def progreso(numero, total):
        if numero % 25 == 0 or numero == total:
            print(f"Procesadas: {numero}/{total}", flush=True)

    print(f"Lote {args.lote} | norma {args.norma} | {len(rutas)} documentos | OCR {'activado' if args.ocr else 'desactivado'}", flush=True)
    print(f"Excel: {len(proveedores)} proveedores. Cargando referencias del ERP...", flush=True)
    pipeline.iniciar()
    try:
        inf = pipeline.procesar_lote(
            args.lote, rutas, args.norma,
            sincronizar=contenedor.settings.usar_erp_http and not getattr(args, "sin_sync", False),
            progreso=progreso,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"No se pudo completar el lote: {exc}", file=sys.stderr)
        return 2

    if inf.sincronizacion:
        print("ERP:", _resumen_sync(inf.sincronizacion))
    for aviso in inf.avisos:
        print("AVISO:", aviso)
    print(f"Datos: ERP {inf.ejecucion.version_erp} | Excel {inf.ejecucion.version_excel} | ejecución #{inf.ejecucion.id}")
    print(f"Lectura: {inf.leidos_ahora} leídos ahora, {inf.desde_cache} ya leídos")
    por_nombre = {ruta.name: ruta for ruta in rutas}
    print("\nRESULTADOS", flush=True)
    for indice, decision in enumerate(inf.decisiones, 1):
        print("\n" + "=" * 72)
        print(f"[{indice:03d}/{len(inf.decisiones):03d}] {texto_seguro(decision.file_id)}")
        print("\nTEXTO EXTRAIDO:")
        print(texto_seguro(contenedor.texto_extraido(por_nombre[decision.file_id]) or "(No se pudo recuperar texto)"))
        print(f"\nRESULTADO: {decision.resultado}")
        print(f"MOTIVO: {texto_seguro(decision.motivo)}", flush=True)
        if decision.alertas:
            print("ALERTAS: " + texto_seguro("; ".join(decision.alertas)), flush=True)

    r = inf.ejecucion.resumen
    print("\nRESUMEN")
    for estado in ("PAGAR", "NO_PAGAR", "ESCALAR"):
        print(f"  {estado}: {r[estado]}")
    print(f"{len(inf.decisiones)} facturas en {inf.segundos_lectura + inf.segundos_decision + r.get('segundos_notas', 0):.1f}s")
    if r["tokens_in"] or r["coste_eur"]:
        print(f"IA: {r['tokens_in']} tokens de entrada, {r['tokens_out']} de salida, {r['coste_eur']:.4f} EUR")
    if r.get("notas_evaluadas"):
        print(f"Notas: {r['notas_evaluadas']} documentos, {r['notas_desde_cache']} desde caché, "
              f"{r['notas_fallidas']} evaluaciones no disponibles")
    if args.salida:
        salida = guardar_jsonl([d.outcome for d in inf.decisiones], args.salida)
        print(f"Informe guardado en {salida}")
    if inf.anterior:
        print(f"Respecto a la ejecución #{inf.anterior.id} ({inf.anterior.inicio.astimezone():%d/%m %H:%M}, datos {inf.anterior.version_datos}): "
              f"{len(inf.cambios)} facturas cambian de resultado")
        for c in inf.cambios[:15]:
            print(texto_seguro(f"  {c.file_id}: {c.antes} -> {c.despues} ({c.motivo})"))
        if len(inf.cambios) > 15:
            print(f"  ... y {len(inf.cambios) - 15} más")
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    p = argparse.ArgumentParser(prog="upistas")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Sincroniza el ERP, lee y decide un lote")
    run.add_argument("--lote", default="lote1")
    run.add_argument("--facturas", type=Path, help="Carpeta de PDFs; por defecto CAJA_DIR/facturas")
    run.add_argument("--carpeta", help="Carpeta con documentos, incluidos los que no son PDF")
    run.add_argument("--excel", type=Path, help="Maestro con hojas Proveedores y Pedidos_2026")
    run.add_argument("--erp-snapshot", type=Path, help="JSON: lista de asientos con id, pedido, proveedor_id, nif, importe decimal, fecha y estado")
    run.add_argument("--erp-url", default=settings.erp_url, help="URL del bridge HTTP; por defecto ERP_URL o http://127.0.0.1:8009")
    run.add_argument("--ocr", action="store_true", help="Habilita OCR para escaneos (OCR_PROVIDER=fal|firecrawl); fal requiere FAL_KEY y el extra ocr, firecrawl FIRECRAWL_API_KEY")
    run.add_argument("--norma", default="v3")
    run.add_argument("--timeout-lectura", type=float, default=settings.lectura_timeout_s, help="Segundos máximos por documento, incluida la llamada OCR")
    run.add_argument("--salida", help="Opcional: guardar además un informe JSONL en outputs")
    run.add_argument("--limit", type=int, default=0, help="Procesar solo los N primeros (pruebas)")
    run.add_argument("--sin-sync", action="store_true", help="No hablar con el ERP: usar la última copia")
    run.set_defaults(func=cmd_run)
    extract = sub.add_parser("extract", help="Extrae campos sin Excel, ERP ni decisiones de pago")
    extract.add_argument("--facturas", type=Path, help="Carpeta de PDFs; por defecto CAJA_DIR/facturas")
    extract.add_argument("--ocr", action="store_true", help="Habilita OCR de pago (OCR_PROVIDER=fal|firecrawl); fal requiere FAL_KEY y el extra ocr, firecrawl FIRECRAWL_API_KEY")
    extract.add_argument("--limit", type=int, default=0)
    extract.add_argument("--timeout-lectura", type=float, default=settings.lectura_timeout_s)
    extract.add_argument("--salida", default="extraidas.jsonl")
    extract.set_defaults(func=cmd_extract)
    erp = sub.add_parser("erp", help="Conexión con el ERP de Alberto")
    erp.add_argument("accion", choices=["sync", "estado"])
    erp.set_defaults(func=cmd_erp)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
