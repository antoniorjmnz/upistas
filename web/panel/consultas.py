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
from upistas.dominio.importes import normaliza_iban
from web.panel.models import Decision, Ejecucion, Lectura, Proveedor, RevisionHumana

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
    "R0_lectura": "Se ha podido leer todo lo que hace falta",
    "R1_nif_iban": "Proveedor conocido y su cuenta bancaria",
    "R2_pedido_importe": "El pedido existe y el importe coincide",
    "R3_iva_total": "IVA bien calculado y total correcto",
    "R3_datos_fiscales": "Importes y tipo de IVA legibles",
    "R4_fecha": "Fecha válida y no futura",
    "R5_erp_pendiente": "Pendiente de pago en el ERP y no pagado antes",
    "R5_no_pagada": "No pagado ya en el ERP",
    "R5_duplicado": "No es una factura repetida",
    "R5_hash_previo": "No aprobada ya en otro lote",
    "R5_copia_hash": "No es copia de otra factura del lote",
    "R5_reenvio": "No es un reenvío de otra factura",
    "R6_notas": "Sin texto que intente influir en la decisión",
    "R6_contenido_oculto": "Sin texto escondido ni contenido raro",
    "R6_evaluacion_disponible": "Sus notas se han podido evaluar",
    "R6_maestro_verificable": "Sus datos se han podido contrastar con el maestro",
    "R6_proveedor_referencias": "El proveedor del pedido cuadra entre el maestro y el ERP",
    "R6_revision_interna": "Sin notas que pidan revisión",
    "R7_marcado_por_alberto": "No apuntada por Alberto para revisar",
    "R8_importe_anomalo": "Importe dentro de lo habitual",
    "R9_destinatario": "Dirigida a Banco Miralmar",
    "R10_fichero_sospechoso": "Fichero sin contenido raro",
}


def nombre_regla(id_regla: str) -> str:
    """El nombre en palabras; si la regla es nueva y aún no tiene nombre, algo legible («Comprobación 11»), nunca el id."""
    if id_regla in NOMBRE_REGLA:
        return NOMBRE_REGLA[id_regla]
    numero = id_regla[1:].split("_", 1)[0] if id_regla.startswith("R") else ""
    return f"Comprobación {numero}" if numero.isdigit() else "Otra comprobación"


def nombre_norma(norma: str | None) -> str:
    """"v3" → "versión 3 de la norma"; cualquier otro nombre, «la norma» tal cual, sin códigos."""
    texto = str(norma or "").strip()
    if texto.lower().startswith("v") and texto[1:].isdigit():
        return f"versión {texto[1:]} de la norma"
    return "norma en vigor"


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
    "R0_lectura": "No se ha podido leer bien la factura",
    "R3_datos_fiscales": "Faltan importes legibles para comprobar el IVA",
    "R5_hash_previo": "Ya se aprobó antes esta misma factura",
    "R5_copia_hash": "Es una copia de una factura ya vista",
    "R5_reenvio": "Es un reenvío de una factura anterior",
    "R6_evaluacion_disponible": "No se ha podido evaluar la nota que trae",
    "R6_contenido_oculto": "Trae texto escondido o contenido raro",
    "R6_proveedor_referencias": "El proveedor del pedido no cuadra entre el Excel y el ERP",
    "R6_revision_interna": "Trae una nota que pide revisión",
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


# --- El PDF con las alarmas señaladas: lo que el caso de uso `marcar_pdf` necesita saber de la decisión ---

# Cada dato leído, como se le nombra a Alberto dentro de una frase («no se ha podido leer la fecha»).
NOMBRE_CAMPO = {
    "nif": "el NIF del proveedor",
    "iban": "la cuenta donde cobra",
    "pedido": "el número de pedido",
    "fecha": "la fecha",
    "base": "la base imponible",
    "iva": "el IVA",
    "total": "el total",
}


def hay_algo_que_marcar(decision: Decision) -> bool:
    """Si el PDF marcado enseñaría algo: alguna comprobación que falla y no es solo que no se pudo leer,
    o avisos del fichero. Una escaneada que solo falla por lectura abriría un PDF sin ninguna marca."""
    reglas = (decision.outcome or {}).get("reglas") or []
    if any(not r.get("ok") and r.get("id") != "R0_lectura" for r in reglas):
        return True
    return bool((decision.documento.alertas or []) + (decision.alertas or []))


def alarmas_de(decision: Decision, lectura: Lectura | None):
    """Lo que hizo saltar las alarmas en esa decisión, listo para que `marcar_pdf` lo señale en el PDF:
    las comprobaciones que fallan (en palabras de Alberto), los datos leídos con su texto literal, las notas,
    los avisos del fichero y lo que no se pudo leer."""
    from upistas.aplicacion.mapeo import CONFIANZA_MINIMA
    from upistas.aplicacion.marcar_pdf import Alarmas, CampoLeido, ReglaFallida

    extraida = (lectura.extraida if lectura else None) or {}
    campos = extraida.get("campos") or {}
    leidos = {nombre: CampoLeido(c.get("valor"), c.get("fuente")) for nombre, c in campos.items() if c}

    def leido(nombre: str) -> bool:
        c = campos.get(nombre) or {}
        return c.get("valor") not in (None, "") and (c.get("confianza") or 0) >= CONFIANZA_MINIMA

    reglas = tuple(
        ReglaFallida(r.get("id") or "", r.get("detalle") or "", MOTIVO_CORTO.get(r.get("id") or "", ""))
        for r in (decision.outcome or {}).get("reglas") or [] if not r.get("ok")
    )
    notas = tuple(str(n.get("texto")) for n in (decision.notas or []) if isinstance(n, dict) and n.get("texto"))
    # Las notas ya van rodeadas por su cuenta: como aviso del fichero solo cuentan las del inspector.
    alertas = [a for a in dict.fromkeys((decision.documento.alertas or []) + (decision.alertas or [])) if not a.startswith("Nota:")]
    return Alarmas(
        resultado=ETIQUETA.get(decision.resultado, decision.resultado),
        motivo=motivo_corto(decision),
        reglas=reglas,
        campos=leidos,
        notas=notas,
        sin_leer=tuple(nombre for campo, nombre in NOMBRE_CAMPO.items() if not leido(campo)),
        errores=tuple(str(e) for e in extraida.get("errores") or []),
        alertas=tuple(alertas),
    )


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


def atajos_de_fecha(hoy=None) -> list[dict]:
    """Los periodos que Alberto elige de un golpe: este mes, el pasado, este trimestre, este año."""
    from calendar import monthrange
    from datetime import date, timedelta

    hoy = hoy or date.today()

    def ultimo_dia(a: int, m: int) -> date:
        return date(a, m, monthrange(a, m)[1])

    mes_pasado = hoy.replace(day=1) - timedelta(days=1)
    trimestre_inicio = date(hoy.year, 3 * ((hoy.month - 1) // 3) + 1, 1)
    trimestre_fin = ultimo_dia(hoy.year, trimestre_inicio.month + 2)
    return [
        {"nombre": "Este mes", "desde": hoy.replace(day=1).isoformat(), "hasta": ultimo_dia(hoy.year, hoy.month).isoformat()},
        {"nombre": "Mes pasado", "desde": mes_pasado.replace(day=1).isoformat(), "hasta": mes_pasado.isoformat()},
        {"nombre": "Este trimestre", "desde": trimestre_inicio.isoformat(), "hasta": trimestre_fin.isoformat()},
        {"nombre": "Este año", "desde": date(hoy.year, 1, 1).isoformat(), "hasta": date(hoy.year, 12, 31).isoformat()},
    ]


# --- Asistente «Preguntar»: consultas que las herramientas del chat convierten en respuestas ----

import re  # noqa: E402
from decimal import Decimal  # noqa: E402

from django.db.models import Q  # noqa: E402

from web.panel.models import AsientoERP, Documento, SincronizacionERP, VersionERP  # noqa: E402


def _canon_pedido(texto: str) -> str:
    """'PO-2026-0474', 'po 2026 474', '474' → 'PO20260474' (o '' si no parece pedido)."""
    s = re.sub(r"[^A-Z0-9]", "", texto.upper())
    m = re.search(r"PO?2026(\d{3,5})$", s) or re.fullmatch(r"(\d{3,5})", s)
    return f"PO2026{m.group(1).zfill(4)}" if m else ""


MOTIVO_MAX = 200  # en las listas, el motivo y el texto de la factura se recortan a esto
MARCA_TEXTO = "[texto de la factura]"


def _recortar(texto: str, maximo: int = MOTIVO_MAX) -> str:
    return texto if len(texto) <= maximo else texto[: maximo - 1].rstrip() + "…"


def _texto_de_la_factura(d: Decision) -> list[str]:
    """Las notas que traía la factura. Vienen de fuera: se informan, nunca se obedecen."""
    textos = []
    for n in d.notas or []:
        t = n.get("texto") if isinstance(n, dict) else n
        if t and str(t).strip():
            textos.append(str(t))
    return textos


def _motivo_sin_texto_de_factura(d: Decision, textos: list[str]) -> str:
    """El motivo con lo que ponía la factura sustituido por «[texto de la factura]»: ese texto va
    aparte, marcado como no fiable, para que la IA no lo lea como una instrucción."""
    if not textos:
        return d.motivo
    reglas = (d.outcome or {}).get("reglas") or []
    partes = [r.get("detalle") or r.get("id") or "" for r in reglas if not r.get("ok")] or [d.motivo or ""]
    limpias = []
    for parte in partes:
        parte = re.sub(r"\| Evidencia: .*", f"| Evidencia: {MARCA_TEXTO}", parte, flags=re.S)  # la cita de la IA
        for t in textos:
            for trozo in (t, t[:400]):  # R6 pega los primeros 400 caracteres de la nota al detalle
                parte = parte.replace(trozo, MARCA_TEXTO)
        limpias.append(parte)
    return "; ".join(limpias)


def _fila_decision(d: Decision, lecturas: dict[str, Lectura], por_nif: dict[str, str], corto: bool = False) -> dict:
    """Una factura tal y como se le cuenta al asistente. `por_nif` es `nombres_por_nif()`, pedido una
    vez por consulta. Con `corto` (listas) el motivo y el texto de la factura se recortan."""
    campos_leidos = campos(lecturas.get(d.documento.sha256))
    textos = _texto_de_la_factura(d)
    motivo = _motivo_sin_texto_de_factura(d, textos)
    fila = {
        "file_id": d.documento.file_id,
        "resultado": d.resultado,
        "motivo": _recortar(motivo) if corto else motivo,
        "pedido": d.pedido or None,
        "numero_factura": campos_leidos.get("numero_factura"),
        "proveedor": nombre_proveedor(campos_leidos, por_nif),
        "total": campos_leidos.get("total"),
        "lote": d.ejecucion.lote,
        "norma": d.ejecucion.norma,
    }
    if textos:
        fila["texto_de_la_factura_no_fiable"] = [_recortar(t) for t in textos] if corto else textos
    return fila


def resumen_lote(lote: str | None = None) -> dict:
    """Cuántas facturas se pagan, no se pagan y se escalan en la última ejecución, y cuánto suman."""
    ejecucion = ultima_ejecucion(lote)
    if ejecucion is None:
        return {"aviso": "todavía no hay ninguna ejecución terminada; hay que procesar un lote primero"}
    decisiones = list(decisiones_de(ejecucion))
    lecturas = lecturas_por_sha(d.documento.sha256 for d in decisiones)
    conteo = {r: 0 for r in ("PAGAR", "NO_PAGAR", "ESCALAR")}
    a_pagar = Decimal("0")
    for d in decisiones:
        conteo[d.resultado] = conteo.get(d.resultado, 0) + 1
        if d.resultado == "PAGAR":
            total = campos(lecturas.get(d.documento.sha256)).get("total")
            if total is not None:
                a_pagar += Decimal(str(total))
    return {
        "lote": ejecucion.lote,
        "norma": ejecucion.norma,
        "version_datos": ejecucion.version_datos,
        "cuando": ejecucion.fin.isoformat() if ejecucion.fin else None,
        "facturas": len(decisiones),
        "pagar": conteo["PAGAR"],
        "no_pagar": conteo["NO_PAGAR"],
        "escalar": conteo["ESCALAR"],
        "importe_a_pagar": float(a_pagar),
    }


LIMITE_MAXIMO = 100  # filas como mucho en una lista del asistente, pida lo que pida el modelo


def acotar_limite(limite, defecto: int) -> int:
    """El `limite` que pide el modelo, entre 1 y LIMITE_MAXIMO; si no es un número, el de siempre."""
    try:
        n = int(limite)
    except (TypeError, ValueError):
        return defecto
    return max(1, min(n, LIMITE_MAXIMO))


def buscar_facturas(texto: str, limite: int = 10) -> dict:
    """Facturas de la última ejecución que coinciden con un nombre de fichero, nº de factura,
    pedido, NIF o nombre de proveedor: las `limite` primeras, y cuántas hay en total."""
    ejecucion = ultima_ejecucion()
    if ejecucion is None:
        return {"aviso": "todavía no hay ninguna ejecución terminada"}
    texto = (texto or "").strip()
    if not texto:
        return {"aviso": "no has dicho qué buscar"}
    limite = acotar_limite(limite, 10)
    shas = Lectura.objects.filter(
        Q(extraida__campos__numero_factura__valor__icontains=texto)
        | Q(extraida__campos__proveedor_nombre__valor__icontains=texto)
        | Q(extraida__campos__nif__valor__icontains=texto)
    ).values("sha256")
    canon = _canon_pedido(texto)
    filtro = (
        Q(documento__file_id__icontains=texto)
        | Q(pedido__icontains=texto)
        | Q(documento__sha256__in=shas)
    )
    if canon:
        filtro |= Q(pedido__icontains=canon[6:])  # los dígitos del pedido: "2026-0474", "PO20260474"...
    todas = decisiones_de(ejecucion).filter(filtro)
    total = todas.count()
    decisiones = list(todas[:limite])
    lecturas = lecturas_por_sha(d.documento.sha256 for d in decisiones)
    por_nif = nombres_por_nif()
    return {
        "ejecucion": ejecucion.lote,
        "encontradas": [_fila_decision(d, lecturas, por_nif, corto=True) for d in decisiones],
        "total": total,
        "mas": total - len(decisiones),
    }


def _reglas_sin_texto(reglas):
    """Las comprobaciones sin el texto literal de la factura: la IA lo recibe como aviso, nunca como dato."""
    limpias = []
    for r in reglas or []:
        r = dict(r)
        detalle = r.get("detalle")
        if isinstance(detalle, str) and r.get("id") in ("R6_notas", "R6_contenido_oculto", "R6_revision_interna"):
            r["detalle"] = detalle.split(": ", 1)[0].split(" | Evidencia", 1)[0]
        limpias.append(r)
    return limpias


def detalle_factura(file_id: str) -> dict:
    """Todo lo que sabemos de una factura: qué se leyó, qué reglas aplicaron y por qué salió así."""
    documento = Documento.objects.filter(file_id__iexact=file_id.strip()).order_by("-primera_vez").first()
    if documento is None:
        parecidas = list(
            Documento.objects.filter(file_id__icontains=file_id.strip()).values_list("file_id", flat=True)[:5]
        )
        return {"aviso": f"no hay ninguna factura «{file_id}»", "parecidas": parecidas}
    decision = (
        Decision.objects.filter(documento=documento, ejecucion__estado="terminada")
        .select_related("ejecucion").order_by("-ejecucion__inicio").first()
    )
    lectura = Lectura.objects.filter(sha256=documento.sha256).first()
    revision = RevisionHumana.objects.filter(documento=documento).first()
    campos_leidos = campos(lectura)
    # La cuenta bancaria no se le cuenta entera a la IA: solo el final y si es la del maestro.
    iban_leido = normaliza_iban(campos_leidos.get("iban"))
    nif_leido = str(campos_leidos.get("nif") or "").upper().replace(" ", "")
    proveedor = Proveedor.objects.filter(nif=nif_leido).first() if nif_leido else None
    return {
        "file_id": documento.file_id,
        "lote": documento.lote,
        "tipo": documento.tipo,
        "paginas": documento.paginas,
        "alertas_fichero": list(documento.alertas or []),
        "decision": _fila_decision(decision, {documento.sha256: lectura}, nombres_por_nif()) if decision else None,
        "reglas": _reglas_sin_texto((decision.outcome or {}).get("reglas")) if decision else None,
        "lectura": (
            {
                "metodo": lectura.metodo,
                "lector": lectura.lector,
                "modelo": lectura.modelo,
                "segundos": lectura.segundos,
                "tokens": lectura.tokens_in + lectura.tokens_out,
                "coste_eur": lectura.coste_eur,
                "campos": {
                    **{n: campos_leidos.get(n) for n in ("numero_factura", "proveedor_nombre", "nif", "pedido", "fecha", "base", "iva", "total")},
                    "iban": f"…{iban_leido[-4:]}" if iban_leido else None,
                    "iban_coincide": (iban_leido == proveedor.iban) if iban_leido and proveedor else None,
                },
            }
            if lectura else None
        ),
        "revision_humana": (
            {"resultado": revision.resultado, "quien": revision.quien, "comentario": revision.comentario}
            if revision else None
        ),
    }


def pendientes_revision(lote: str | None = None, limite: int = 15) -> dict:
    """Facturas escaladas de la última ejecución que nadie ha revisado todavía (las `limite` primeras)."""
    ejecucion = ultima_ejecucion(lote)
    if ejecucion is None:
        return {"aviso": "todavía no hay ninguna ejecución terminada"}
    limite = acotar_limite(limite, 15)
    todas = pendientes_de_revision(ejecucion)
    total = todas.count()
    decisiones = list(todas[:limite])
    lecturas = lecturas_por_sha(d.documento.sha256 for d in decisiones)
    por_nif = nombres_por_nif()
    return {
        "ejecucion": ejecucion.lote,
        "pendientes": [_fila_decision(d, lecturas, por_nif, corto=True) for d in decisiones],
        "total": total,
        "mas": total - len(decisiones),
    }


def estado_pedido(pedido: str) -> dict:
    """Qué dice la copia del ERP sobre un pedido: asiento, importe y si ya está pagado."""
    en_uso = SincronizacionERP.objects.filter(ok=True).first()
    if en_uso is None or not en_uso.version_id:
        return {"aviso": "todavía no hay copia del ERP; hay que sincronizar en «Conexión con el ERP»"}
    canon = _canon_pedido(pedido)
    if not canon:
        return {"aviso": f"«{pedido}» no parece un número de pedido (PO-2026-NNNN)"}
    asiento = next(
        (a for a in AsientoERP.objects.filter(version_id=en_uso.version_id)
         if _canon_pedido(a.pedido) == canon),
        None,
    )
    if asiento is None:
        return {"aviso": f"el pedido {pedido} no está en la copia del ERP (versión {en_uso.version_id})"}
    decision = (
        Decision.objects.filter(pedido=asiento.pedido, ejecucion__estado="terminada")
        .select_related("documento", "ejecucion").order_by("-ejecucion__inicio").first()
    )
    return {
        "pedido": asiento.pedido,
        "asiento": asiento.asiento_id,
        "proveedor_id": asiento.proveedor_id,
        "nif": asiento.nif or None,
        "importe": float(asiento.importe),
        "fecha": asiento.fecha.isoformat() if asiento.fecha else None,
        "estado_erp": asiento.estado,
        "version_erp": en_uso.version_id,
        "decision_nuestra": (
            {"file_id": decision.documento.file_id, "resultado": decision.resultado, "motivo": decision.motivo}
            if decision else None
        ),
    }


def cambios_erp() -> dict:
    """Qué cambió en el ERP entre la copia en uso y la anterior (lote 2, el dato del domingo...)."""
    from upistas.adaptadores.persistencia.django_erp import AlmacenERPDjango
    from upistas.dominio.versiones import diferencias

    # Las versiones se ordenan por su sincronización (id autoincremental), no por `creada`:
    # dos descargas pueden llevar el mismo timestamp y el orden saldría al revés.
    sincs = SincronizacionERP.objects.filter(ok=True).values_list("version_id", flat=True)
    ultimas = list(dict.fromkeys(sincs))[:2]  # SincronizacionERP ordena -inicio,-id: primero la en uso
    if len(ultimas) < 2:
        return {"aviso": "solo hay una versión del ERP; no hay nada con lo que comparar"}
    antes = VersionERP.objects.get(pk=ultimas[1])
    despues = VersionERP.objects.get(pk=ultimas[0])
    almacen = AlmacenERPDjango()
    d = diferencias(almacen.asientos(antes.pk), almacen.asientos(despues.pk))
    return {
        "de": antes.pk,
        "a": despues.pk,
        "nuevos": list(d.nuevos),
        "eliminados": list(d.eliminados),
        "modificados": [
            {"asiento": c.asiento, "campo": c.campo, "antes": c.antes, "despues": c.despues}
            for c in d.modificados
        ],
        "pedidos_afectados": sorted(d.pedidos_afectados),
        "aviso": "no hay diferencias entre las dos últimas copias" if d.vacias else None,
    }


def estado_sincronizacion() -> dict:
    """Cómo va la conexión con el ERP: última sincronización y versión en uso."""
    ultima = SincronizacionERP.objects.select_related("version").first()
    if ultima is None:
        return {"aviso": "nunca se ha sincronizado con el ERP"}
    return {
        "cuando": ultima.inicio.isoformat(),
        "ok": ultima.ok,
        "version": ultima.version_id,
        "asientos": ultima.n_asientos,
        "lote2_cargado": ultima.lote2_cargado,
        "error": ultima.error or None,
        "cambios": {"nuevos": ultima.nuevos, "modificados": ultima.modificados, "eliminados": ultima.eliminados},
    }


# --- Asistente: el resto de lo que enseña la web (maestro, decisiones de Alberto, repasos, importaciones) ---

from web.panel.models import Importacion, Pedido  # noqa: E402


def buscar_proveedor(texto: str) -> Proveedor | None:
    """Un proveedor del maestro por código (P001), NIF o trozo del nombre. Con varios del mismo nombre, el primero."""
    limpio = str(texto or "").strip()
    if not limpio:
        return None
    return (
        Proveedor.objects.filter(Q(codigo__iexact=limpio) | Q(nif__iexact=limpio.replace(" ", ""))).first()
        or Proveedor.objects.filter(nombre__icontains=limpio).order_by("nombre").first()
    )


def _iban_enmascarado(iban: str | None) -> str | None:
    """Solo las cuatro últimas cifras: la cuenta entera no se le cuenta a la IA."""
    limpio = normaliza_iban(iban)
    return f"…{limpio[-4:]}" if limpio else None


def _pedido_corto(p: Pedido) -> dict:
    fila = {"numero": p.numero, "importe": float(p.importe), "fecha": p.fecha.isoformat() if p.fecha else None}
    if p.revisar:
        fila["marcado_para_revisar"] = True
    if p.nota:
        fila["nota"] = _recortar(p.nota)
    return fila


def proveedor(texto: str) -> dict:
    """La ficha del maestro de un proveedor: quién es, cuenta enmascarada, condiciones y sus pedidos
    (cuántos, y cuáles apuntó Alberto para revisar con qué nota)."""
    p = buscar_proveedor(texto)
    if p is None:
        parecidos = list(Proveedor.objects.filter(nombre__icontains=str(texto or "").strip()[:40]).values_list("nombre", flat=True)[:5])
        return {"aviso": f"no hay ningún proveedor «{texto}» en el maestro (vale el código, el NIF o el nombre)", "parecidos": parecidos}
    pedidos = list(p.pedidos.order_by("numero"))
    marcados = [q for q in pedidos if q.revisar]
    return {
        "codigo": p.codigo,
        "nombre": p.nombre,
        "nif": p.nif,
        "iban": _iban_enmascarado(p.iban),
        "ciudad": p.ciudad or None,
        "dias_de_pago": p.condiciones_dias,
        "activo": p.activo,
        "pedidos": len(pedidos),
        "importe_pedidos": float(sum((q.importe for q in pedidos), Decimal("0"))),
        "marcados_para_revisar": [_pedido_corto(q) for q in marcados],
        "con_nota": [_pedido_corto(q) for q in pedidos if q.nota and not q.revisar],
    }


def decisiones_de_alberto(lote: str | None = None, limite: int = 15) -> dict:
    """Lo que Alberto decidió a mano sobre las facturas escaladas (RevisionHumana), de la más reciente atrás."""
    limite = acotar_limite(limite, 15)
    qs = RevisionHumana.objects.select_related("documento").order_by("-cuando", "-id")
    if lote:
        qs = qs.filter(documento__lote=lote)
    total = qs.count()
    filas = list(qs[:limite])
    return {
        "decisiones": [
            {
                "file_id": r.documento.file_id,
                "lote": r.documento.lote,
                "decidio": r.resultado,
                "comentario": _recortar(r.comentario) if r.comentario else None,
                "quien": r.quien,
                "cuando": r.cuando.isoformat(),
            }
            for r in filas
        ],
        "total": total,
        "mas": total - len(filas),
    }


def _cambios_baratos(ejecucion: Ejecucion) -> dict | None:
    """Qué facturas cambiaron de resultado respecto al repaso anterior del mismo lote, con una sola consulta
    ligera (id, fichero y resultado): cuántas y las cinco primeras. Nada si no hay repaso anterior."""
    anterior = anterior_a(ejecucion)
    if anterior is None:
        return None
    resultados: dict[int, dict[str, str]] = {anterior.id: {}, ejecucion.id: {}}
    for eid, file_id, resultado in Decision.objects.filter(ejecucion_id__in=(anterior.id, ejecucion.id)).values_list(
        "ejecucion_id", "documento__file_id", "resultado"
    ):
        resultados[eid][file_id] = resultado
    antes, despues = resultados[anterior.id], resultados[ejecucion.id]
    cambios = [
        {"file_id": f, "antes": antes[f], "despues": r}
        for f, r in sorted(despues.items()) if f in antes and antes[f] != r
    ]
    return {"respecto_a": anterior.inicio.isoformat(), "cuantos": len(cambios), "primeros": cambios[:5]}


def repasos(limite: int = 10) -> dict:
    """El registro de repasos (Ejecucion): cuándo, qué lote y norma, cuánto tardó, cuántas se pagan, no se
    pagan o escalan, y qué cambió respecto al repaso anterior del mismo lote."""
    limite = acotar_limite(limite, 10)
    qs = Ejecucion.objects.all()
    total = qs.count()
    filas = []
    for e in qs[:limite]:
        c = cifras(e)
        fila = {
            "id": e.id,
            "cuando": e.inicio.isoformat(),
            "lote": e.lote,
            "norma": e.norma,
            "estado": e.estado,
            "version_datos": e.version_datos,
            "segundos": round(c["segundos"], 1) if c["segundos"] else None,
            "facturas": c["documentos"],
            "pagar": c["PAGAR"],
            "no_pagar": c["NO_PAGAR"],
            "escalar": c["ESCALAR"],
            "coste_eur": c["coste_eur"],
        }
        if e.estado == "terminada":
            fila["cambios_respecto_al_anterior"] = _cambios_baratos(e)
        filas.append(fila)
    return {"repasos": filas, "total": total, "mas": total - len(filas)}


def importaciones(limite: int = 10) -> dict:
    """Las veces que Alberto aplicó un fichero de proveedores o pedidos desde «Importar datos»."""
    limite = acotar_limite(limite, 10)
    qs = Importacion.objects.all()
    total = qs.count()
    filas = list(qs[:limite])
    return {
        "importaciones": [
            {"cuando": i.cuando.isoformat(), "ficheros": i.ficheros, "nuevos": i.nuevos, "cambiados": i.cambiados, "invalidos": i.invalidos}
            for i in filas
        ],
        "total": total,
        "mas": total - len(filas),
    }


# --- Por qué se decide así: cada regla explicada en llano (alineado con normas/v3.toml y docs/flujo_decision.md) ---

# id de regla → (qué comprueba, qué pasa si falla y por qué). `si_falla` sale de la norma; aquí solo las palabras.
EXPLICACION_REGLA = {
    "R0_lectura": (
        "Que se ha podido leer con seguridad todo lo que hace falta: NIF, cuenta, pedido, importes y fecha.",
        "Se manda a revisar. Un dato que no se pudo leer nunca prueba que algo esté mal, así que no se niega el pago: la mira una persona.",
    ),
    "R1_nif_iban": (
        "Que el NIF de la factura está en el maestro de proveedores y que la cuenta bancaria es exactamente la que hay en el maestro.",
        "No se paga. Es la regla 1 de la norma: una cuenta distinta es la estafa más habitual, y una nota diciendo que el proveedor ha cambiado de cuenta no vale; la cuenta se cambia en la ficha del proveedor, no en una factura.",
    ),
    "R2_pedido_importe": (
        "Que el pedido existe, es de ese mismo proveedor y el importe de la factura es igual al del pedido (con un margen de un céntimo).",
        "No se paga. Es la regla 2: sin pedido, con el pedido de otro proveedor o con un importe distinto, la factura no cuadra con lo que se encargó.",
    ),
    "R3_iva_total": (
        "Que el IVA está bien calculado (base por el tipo impreso) y que el total es la base más el IVA, con margen de un céntimo.",
        "No se paga. Es la regla 3: una suma mal hecha o una cuota que no corresponde al tipo es un incumplimiento probado.",
    ),
    "R3_datos_fiscales": (
        "Que hay importes legibles y no negativos, y un tipo de IVA impreso con el que contrastar la cuota.",
        "Se manda a revisar. Sin esos datos no se puede aplicar la regla del IVA con seguridad (duda fiscal), y una duda no es un incumplimiento.",
    ),
    "R4_fecha": (
        "Que la fecha de la factura es una fecha real y no está en el futuro.",
        "No se paga. Es la regla 4: una fecha imposible (31/02) o futura leída con claridad incumple la norma. Si la fecha no se pudo leer, eso lo trata la comprobación de lectura y va a revisar.",
    ),
    "R5_erp_pendiente": (
        "Que el pedido tiene un asiento en la copia del ERP, que está PENDIENTE de pago y que no se aprobó ya en otra decisión.",
        "Se manda a revisar. Sin apunte en el ERP, con apuntes que se contradicen o con un estado que no es pendiente falta la referencia oficial para pagar.",
    ),
    "R5_no_pagada": (
        "Que el ERP no dice ya PAGADA para ese pedido y que no se aprobó en otro lote.",
        "No se paga. Es la regla 5: nunca se paga dos veces lo mismo.",
    ),
    "R5_hash_previo": (
        "Que este mismo documento (mismo contenido, aunque cambie el nombre) no se aprobó ya en otro lote.",
        "No se paga. Es la misma factura repetida: pagarla sería pagar dos veces.",
    ),
    "R5_copia_hash": (
        "Que no es una copia exacta (mismo contenido) de otra factura del lote.",
        "No se paga: se paga la primera y las copias no son un cobro nuevo.",
    ),
    "R5_reenvio": (
        "Que no es un reenvío de otra factura del lote para el mismo pedido, cuando está claro cuál es la original.",
        "No se paga: se paga la original y el reenvío sería pagar dos veces.",
    ),
    "R5_duplicado": (
        "Que no hay varias facturas distintas para el mismo pedido sin que esté claro cuál es la buena.",
        "Se mandan todas a revisar: solo una persona puede decir cuál se paga.",
    ),
    "R6_notas": (
        "Que la factura no trae notas que intenten influir en el pago (urgencias, cambios de cuenta, «pague sin comprobar»).",
        "Se manda a revisar, aunque el ERP diga que ya está pagada. El texto de una factura nunca decide: ni autoriza ni bloquea un pago; lo lee Alberto con el motivo delante.",
    ),
    "R6_contenido_oculto": (
        "Que no hay texto escondido (letra blanca, caracteres invisibles, capas ocultas) en el PDF.",
        "Se manda a revisar. Un fichero con contenido oculto es sospechoso y lo mira una persona.",
    ),
    "R6_evaluacion_disponible": (
        "Que, si la factura trae notas, se ha podido evaluar qué dicen.",
        "Se manda a revisar: hay notas y no se sabe qué piden, así que no se da por buena.",
    ),
    "R6_maestro_verificable": (
        "Que el maestro tiene NIF y cuenta del proveedor del pedido para poder contrastarlos.",
        "Se manda a revisar. Si la ficha del proveedor está incompleta no se puede probar nada, ni a favor ni en contra: hay que completar la ficha en Proveedores.",
    ),
    "R6_proveedor_referencias": (
        "Que el Excel de pedidos y el ERP dicen el mismo proveedor para ese pedido, y que coincide con el NIF de la factura.",
        "Se manda a revisar: las dos fuentes se contradicen y hay que ver cuál tiene razón.",
    ),
    "R6_revision_interna": (
        "Que Alberto no apuntó ese pedido para revisar (la marca «revisar» del pedido).",
        "Se manda a revisar, porque lo pidió él: la marca se quita en la ficha del pedido.",
    ),
    "R7_marcado_por_alberto": (
        "Que Alberto no apuntó ese pedido para revisar.",
        "Se manda a revisar, porque lo pidió él.",
    ),
    "R8_importe_anomalo": (
        "Que el importe está dentro de lo habitual para ese proveedor.",
        "Se manda a revisar: un importe muy fuera de lo normal no es un error probado, pero conviene mirarlo.",
    ),
    "R9_destinatario": (
        "Que la factura va dirigida a la empresa de Alberto (Banco Miralmar) y no a otro cliente.",
        "Se manda a revisar: una factura para otro no se paga sin que alguien lo confirme.",
    ),
    "R10_fichero_sospechoso": (
        "Que el fichero no trae contenido raro (scripts, adjuntos, capas escondidas).",
        "Se manda a revisar: el fichero puede estar manipulado.",
    ),
}

# El flujo entero en cinco frases, para que el asistente lo cuente sin una factura delante (menos de 120 palabras).
RESUMEN_FLUJO = (
    "Cómo se decide cada factura: primero se lee todo y, si algo no se pudo leer con seguridad, "
    "se manda a revisar; nunca se niega el pago por eso. "
    "Después se comprueba que el proveedor y su cuenta son los del maestro, que el pedido existe con ese importe, "
    "que la fecha es válida y que el IVA y el total cuadran: si falla alguna, no se paga. "
    "Si trae notas que intentan influir, texto oculto o Alberto la apuntó, se manda a revisar. "
    "Por último el ERP: ya pagada, no se paga; sin apunte, a revisar; si todo pasa, se paga. "
    "Si fallan varias manda la más grave: no pagar antes que revisar, y revisar antes que pagar."
)

_ETIQUETA_SI_FALLA = {"NO_PAGAR": "no se paga", "ESCALAR": "se manda a revisar", "PAGAR": "se paga"}
# Las repetidas se resuelven en dominio/duplicados.py, fuera del toml: su resultado va aquí.
_SI_FALLA_FUERA_DE_NORMA = {"R5_copia_hash": "NO_PAGAR", "R5_reenvio": "NO_PAGAR", "R5_duplicado": "ESCALAR"}


def _si_falla_segun_la_norma(version: str = "v3") -> dict[str, str]:
    """Qué provoca cada regla al fallar según normas/<version>.toml (la que manda). Vacío si no se puede leer."""
    try:
        from upistas.infra.contenedor import norma

        return {**_SI_FALLA_FUERA_DE_NORMA, **{r.nombre: r.si_falla.value for r in norma(version).reglas}}
    except Exception:
        return dict(_SI_FALLA_FUERA_DE_NORMA)


def _ficha_regla(id_regla: str, si_falla: dict[str, str]) -> dict:
    comprueba, por_que = EXPLICACION_REGLA[id_regla]
    resultado = si_falla.get(id_regla)
    ficha = {
        "id": id_regla,
        "nombre": nombre_regla(id_regla),
        "comprueba": comprueba,
        "si_falla": _ETIQUETA_SI_FALLA.get(resultado, "depende del caso") if resultado else "según el caso",
        "por_que": por_que,
        "en_una_frase": MOTIVO_CORTO.get(id_regla),
    }
    if id_regla not in si_falla:
        ficha["aviso"] = "esta comprobación no está en la norma en uso; se explica por si sale en una factura antigua"
    return ficha


def explicar_regla(id_o_nombre: str = "") -> dict:
    """La explicación llana de una regla por su id (R1_nif_iban), su número («regla 1», «R5») o una palabra
    de su nombre («iban», «pedido»). Sin argumento, o si no se encuentra, la lista de todas."""
    si_falla = _si_falla_segun_la_norma()
    texto = str(id_o_nombre or "").strip()
    lista = [{"id": r, "nombre": nombre_regla(r), "si_falla": _ETIQUETA_SI_FALLA.get(si_falla.get(r, ""), "según el caso")}
             for r in EXPLICACION_REGLA if r in si_falla]
    if not texto:
        return {"flujo": RESUMEN_FLUJO, "reglas": lista}
    if texto in EXPLICACION_REGLA:
        return {"regla": _ficha_regla(texto, si_falla)}
    llano = texto.lower()
    m = re.fullmatch(r"(?:regla\s*)?r?\s*(\d{1,2})", llano)
    if m:
        prefijo = f"R{int(m.group(1))}_"
        ids = [r for r in EXPLICACION_REGLA if r.startswith(prefijo) and (r in si_falla or not si_falla)]
    else:
        ids = [r for r in EXPLICACION_REGLA if llano in r.lower() or llano in nombre_regla(r).lower() or llano in EXPLICACION_REGLA[r][0].lower()]
    if not ids:
        return {"aviso": f"no hay ninguna regla que se llame «{texto}»", "flujo": RESUMEN_FLUJO, "reglas": lista}
    return {"reglas": [_ficha_regla(r, si_falla) for r in ids[:6]]}
