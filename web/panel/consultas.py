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


def _fila_decision(d: Decision, lecturas: dict[str, Lectura]) -> dict:
    campos_leidos = campos(lecturas.get(d.documento.sha256))
    return {
        "file_id": d.documento.file_id,
        "resultado": d.resultado,
        "motivo": d.motivo,
        "pedido": d.pedido or None,
        "numero_factura": campos_leidos.get("numero_factura"),
        "proveedor": campos_leidos.get("proveedor_nombre"),
        "total": campos_leidos.get("total"),
        "lote": d.ejecucion.lote,
        "norma": d.ejecucion.norma,
    }


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


def buscar_facturas(texto: str, limite: int = 10) -> dict:
    """Facturas de la última ejecución que coinciden con un nombre de fichero, nº de factura,
    pedido, NIF o nombre de proveedor."""
    ejecucion = ultima_ejecucion()
    if ejecucion is None:
        return {"aviso": "todavía no hay ninguna ejecución terminada"}
    texto = (texto or "").strip()
    if not texto:
        return {"aviso": "no has dicho qué buscar"}
    shas = Lectura.objects.filter(
        Q(extraida__campos__numero_factura__valor__icontains=texto)
        | Q(extraida__campos__proveedor_nombre__icontains=texto)
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
    decisiones = list(decisiones_de(ejecucion).filter(filtro)[:limite])
    lecturas = lecturas_por_sha(d.documento.sha256 for d in decisiones)
    return {
        "ejecucion": ejecucion.lote,
        "encontradas": [_fila_decision(d, lecturas) for d in decisiones],
        "mas": decisiones_de(ejecucion).filter(filtro).count() - len(decisiones),
    }


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
    return {
        "file_id": documento.file_id,
        "lote": documento.lote,
        "tipo": documento.tipo,
        "paginas": documento.paginas,
        "alertas_fichero": list(documento.alertas or []),
        "decision": _fila_decision(decision, {documento.sha256: lectura}) if decision else None,
        "reglas": (decision.outcome or {}).get("reglas") if decision else None,
        "lectura": (
            {
                "metodo": lectura.metodo,
                "lector": lectura.lector,
                "modelo": lectura.modelo,
                "segundos": lectura.segundos,
                "tokens": lectura.tokens_in + lectura.tokens_out,
                "coste_eur": lectura.coste_eur,
                "campos": {
                    n: campos_leidos.get(n)
                    for n in ("numero_factura", "proveedor_nombre", "nif", "iban", "pedido", "fecha", "base", "iva", "total")
                },
            }
            if lectura else None
        ),
        "revision_humana": (
            {"resultado": revision.resultado, "quien": revision.quien, "comentario": revision.comentario}
            if revision else None
        ),
    }


def pendientes_revision(lote: str | None = None) -> dict:
    """Facturas escaladas de la última ejecución que nadie ha revisado todavía."""
    ejecucion = ultima_ejecucion(lote)
    if ejecucion is None:
        return {"aviso": "todavía no hay ninguna ejecución terminada"}
    decisiones = list(pendientes_de_revision(ejecucion))
    lecturas = lecturas_por_sha(d.documento.sha256 for d in decisiones)
    return {
        "ejecucion": ejecucion.lote,
        "pendientes": [_fila_decision(d, lecturas) for d in decisiones],
        "cuantas": len(decisiones),
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
