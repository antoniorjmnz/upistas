"""Consultas que comparten varias pantallas. Solo lectura sobre nuestra base de datos.

Vocabulario: un *lote* se procesa en varias *ejecuciones* (cada vez que cambian los datos o la norma);
la que vale es la última terminada. Cada ejecución tiene una *decisión* por documento. La *lectura*
de un documento se busca por su huella (sha256), no por nombre: el mismo contenido se lee una vez.
"""
from __future__ import annotations

from collections.abc import Iterable

from django.db.models import QuerySet

from upistas.adaptadores.persistencia.django_decisiones import RepositorioDecisionesDjango
from upistas.aplicacion.lote import Cambio, comparar
from web.panel.models import Decision, Ejecucion, Lectura, RevisionHumana

CLASE = {"PAGAR": "bien", "NO_PAGAR": "mal", "ESCALAR": "ojo"}
ETIQUETA = {"PAGAR": "Pagar", "NO_PAGAR": "No pagar", "ESCALAR": "Revisar"}


def lotes() -> list[str]:
    return list(Ejecucion.objects.filter(estado="terminada").order_by("lote").values_list("lote", flat=True).distinct())


def ultima_ejecucion(lote: str | None = None) -> Ejecucion | None:
    """La ejecución terminada más reciente (del lote, o de cualquiera)."""
    qs = Ejecucion.objects.filter(estado="terminada")
    if lote:
        qs = qs.filter(lote=lote)
    return qs.first()


def anterior_a(ejecucion: Ejecucion) -> Ejecucion | None:
    return Ejecucion.objects.filter(lote=ejecucion.lote, estado="terminada", inicio__lt=ejecucion.inicio).first()


def decisiones_de(ejecucion: Ejecucion) -> QuerySet[Decision]:
    return Decision.objects.filter(ejecucion=ejecucion).select_related("documento")


def lecturas_por_sha(shas: Iterable[str]) -> dict[str, Lectura]:
    """La lectura más reciente de cada contenido."""
    return {l.sha256: l for l in Lectura.objects.filter(sha256__in=set(shas)).order_by("creada")}


def campos(lectura: Lectura | None) -> dict:
    """Los valores leídos, planos: {"nif": "B46102331", "total": 2489.99, ...}. Vacío si no se leyó."""
    if lectura is None or not lectura.extraida:
        return {}
    return {nombre: (campo or {}).get("valor") for nombre, campo in lectura.extraida.get("campos", {}).items()}


def revisiones_por_documento(lote: str) -> dict[int, RevisionHumana]:
    """La última revisión humana de cada documento del lote, por id de documento."""
    ultimas: dict[int, RevisionHumana] = {}
    for r in RevisionHumana.objects.filter(documento__lote=lote).order_by("cuando", "id"):
        ultimas[r.documento_id] = r
    return ultimas


def pendientes_de_revision(ejecucion: Ejecucion) -> QuerySet[Decision]:
    """Escaladas en esa ejecución sobre las que Alberto no ha dicho nada todavía."""
    revisados = RevisionHumana.objects.filter(documento__lote=ejecucion.lote).values_list("documento_id", flat=True)
    return decisiones_de(ejecucion).filter(resultado="ESCALAR").exclude(documento_id__in=revisados)


def cambios_respecto_a_la_anterior(ejecucion: Ejecucion) -> tuple[Ejecucion | None, list[Cambio]]:
    """Qué facturas cambiaron de resultado respecto a la ejecución anterior del mismo lote."""
    anterior = anterior_a(ejecucion)
    if anterior is None:
        return None, []
    repo = RepositorioDecisionesDjango()
    return anterior, comparar(repo.decisiones(anterior.id), repo.decisiones(ejecucion.id))


# Cómo se le explica cada regla a Alberto (los ids vienen de dominio/reglas y de normas/v3.toml).
NOMBRE_REGLA = {
    "R1_nif_iban": "Proveedor conocido y su cuenta bancaria",
    "R2_pedido_importe": "El pedido existe, es suyo y el importe coincide",
    "R3_iva_total": "IVA bien calculado y total correcto",
    "R4_fecha": "Fecha válida y no futura",
    "R5_erp_pendiente": "Pendiente de pago en el ERP y no pagado antes",
    "R5_no_pagada": "No pagado ya en el ERP",
    "R5_duplicado": "No es una factura repetida",
    "R6_notas": "Sin texto que intente influir en la decisión",
    "R7_marcado_por_alberto": "No apuntada por Alberto para revisar",
    "R8_importe_anomalo": "Importe dentro de lo habitual",
    "R9_destinatario": "Dirigida a Banco Miralmar",
    "R10_fichero_sospechoso": "Fichero sin contenido raro",
}


def nombre_regla(id_regla: str) -> str:
    return NOMBRE_REGLA.get(id_regla, id_regla)


# Cómo se leyó cada factura, dicho para Alberto.
METODOS = {
    "texto_determinista": "leídas del texto del PDF, sin inteligencia artificial",
    "ocr_determinista": "escaneadas, pasadas por reconocimiento de texto",
    "texto_llm": "leídas con ayuda de la inteligencia artificial",
    "vision_llm": "escaneadas, leídas por la inteligencia artificial mirando la imagen",
    "ninguno": "no se pudieron leer",
}


def nombre_lote(lote: str) -> str:
    """"lote1" → "Lote 1". Cualquier otro nombre se deja como está."""
    return f"Lote {lote[4:]}" if lote.startswith("lote") and lote[4:].isdigit() else lote


def cifras(ejecucion: Ejecucion) -> dict:
    """Las cifras de una pasada ya masticadas: cuántas de cada, cuánto tardó y cuánto costó."""
    r = ejecucion.resumen or {}
    documentos = r.get("documentos") or 0
    segundos = r.get("segundos")
    if not segundos and ejecucion.fin:
        segundos = (ejecucion.fin - ejecucion.inicio).total_seconds()
    por_metodo = r.get("por_metodo") or {}
    return {
        "documentos": documentos,
        "PAGAR": r.get("PAGAR") or 0,
        "NO_PAGAR": r.get("NO_PAGAR") or 0,
        "ESCALAR": r.get("ESCALAR") or 0,
        "leidos": r.get("leidos") or 0,
        "segundos": segundos,
        "por_segundo": round(documentos / segundos, 1) if segundos and documentos else None,
        "tokens_in": r.get("tokens_in") or 0,
        "tokens_out": r.get("tokens_out") or 0,
        "coste_eur": r.get("coste_eur") or 0,
        "sin_ia": por_metodo.get("texto_determinista") or 0,
        "metodos": [{"texto": METODOS.get(m, m), "n": n} for m, n in sorted(por_metodo.items(), key=lambda kv: -kv[1])],
    }


# Por qué una factura no se paga o hay que mirarla, en una frase corta para Alberto (por la primera regla que falla).
MOTIVO_CORTO = {
    "R1_nif_iban": "El proveedor o su cuenta no coinciden con el maestro",
    "R2_pedido_importe": "El pedido o el importe no cuadran con el ERP",
    "R3_iva_total": "El IVA o el total no cuadran",
    "R4_fecha": "La fecha no es válida",
    "R5_erp_pendiente": "El ERP dice que ya está pagada",
    "R5_no_pagada": "El ERP dice que ya está pagada",
    "R5_duplicado": "Es una factura repetida",
    "R6_notas": "Trae texto que intenta influir en la decisión",
    "R7_marcado_por_alberto": "Usted la apuntó para revisar",
    "R8_importe_anomalo": "Importe fuera de lo habitual",
    "R9_destinatario": "Va dirigida a otro cliente",
    "R10_fichero_sospechoso": "El fichero trae contenido raro",
}
SIN_LEER = "No se pudo leer la factura"


def motivo_corto(decision: Decision) -> str:
    """Una frase: la primera comprobación que falla, en palabras de Alberto; el motivo entero está en `decision.motivo`."""
    reglas = (decision.outcome or {}).get("reglas") or []
    if not reglas:
        return SIN_LEER if decision.resultado == "ESCALAR" else "Cumple la norma"
    fallan = [r for r in reglas if not r.get("ok")]
    if not fallan:
        return "Cumple la norma" if decision.resultado == "PAGAR" else "Hay dudas con los datos"
    return MOTIVO_CORTO.get(fallan[0].get("id", ""), fallan[0].get("detalle") or "Hay dudas con los datos")


# --- Filtrar por proveedor e importe: lo mismo en Facturas y en Para revisar -------------------


def proveedores_para_filtro() -> list[tuple[str, str]]:
    """(código, nombre) de los proveedores del maestro, por nombre, para el desplegable."""
    from web.panel.models import Proveedor

    return list(Proveedor.objects.order_by("nombre").values_list("codigo", "nombre"))


def importe_o_nada(texto: str | None):
    """'1.200' o '1200,50' → Decimal; vacío o raro → None (no se filtra por eso)."""
    from upistas.dominio.importes import parse_importe

    if not texto or not str(texto).strip():
        return None
    try:
        return parse_importe(str(texto).strip())
    except Exception:
        return None


def fecha_o_nada(texto: str | None):
    """'2026-01-08' (lo que manda un <input type=date>) → date; vacío o raro → None."""
    from datetime import date

    try:
        return date.fromisoformat(str(texto).strip()) if texto and str(texto).strip() else None
    except ValueError:
        return None


def filtrar_decisiones(qs: QuerySet[Decision], proveedor: str = "", desde=None, hasta=None,
                       fecha_desde=None, fecha_hasta=None) -> QuerySet[Decision]:
    """Deja solo las decisiones de ese proveedor (por sus pedidos o por el NIF leído), entre esos importes
    y entre esas fechas de factura (la fecha leída va en ISO, así que se compara como texto)."""
    from django.db.models import Q

    from web.panel.models import Proveedor

    if proveedor:
        p = Proveedor.objects.filter(codigo=proveedor).first()
        if p is None:
            return qs.none()
        pedidos = list(p.pedidos.values_list("numero", flat=True))
        con_su_nif = Lectura.objects.filter(extraida__campos__nif__valor=p.nif).values("sha256")
        qs = qs.filter(Q(pedido__in=pedidos) | Q(documento__sha256__in=con_su_nif))
    if desde is not None or hasta is not None:
        lecturas = Lectura.objects.all()
        if desde is not None:
            lecturas = lecturas.filter(extraida__campos__total__valor__gte=float(desde))
        if hasta is not None:
            lecturas = lecturas.filter(extraida__campos__total__valor__lte=float(hasta))
        qs = qs.filter(documento__sha256__in=lecturas.values("sha256"))
    if fecha_desde is not None or fecha_hasta is not None:
        lecturas = Lectura.objects.all()
        if fecha_desde is not None:
            lecturas = lecturas.filter(extraida__campos__fecha__valor__gte=fecha_desde.isoformat())
        if fecha_hasta is not None:
            lecturas = lecturas.filter(extraida__campos__fecha__valor__lte=fecha_hasta.isoformat())
        qs = qs.filter(documento__sha256__in=lecturas.values("sha256"))
    return qs


# --- El nombre del proveedor: lo que leyó el lector o, si no, el maestro por su NIF ------------


def nombres_por_nif() -> dict[str, str]:
    from web.panel.models import Proveedor

    return dict(Proveedor.objects.values_list("nif", "nombre"))


def nombre_proveedor(campos: dict, por_nif: dict[str, str] | None = None) -> str | None:
    """El nombre leído en la factura; si el lector no lo sacó, el del maestro para ese NIF."""
    nombre = campos.get("proveedor_nombre")
    if nombre:
        return str(nombre)
    nif = campos.get("nif")
    if not nif:
        return None
    tabla = por_nif if por_nif is not None else nombres_por_nif()
    return tabla.get(str(nif).upper().replace(" ", ""))
