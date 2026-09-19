"""Fixtures de la web: un usuario con sesión y un lote pequeño ya decidido, con su ejecución anterior.

`lote_de_prueba` deja en la base de datos cinco facturas con todos los casos que las pantallas tienen
que enseñar: una que se paga, una que no (pedido ya pagado en el ERP; en la ejecución anterior se pagaba),
una escalada por importe anómalo con una nota que mete prisa, una que se paga pero trae alertas del
fichero, y un escaneado que no se pudo leer.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from django.utils import timezone

REGLAS = [
    "R1_nif_iban", "R2_pedido_importe", "R3_iva_total", "R4_fecha", "R5_erp_pendiente", "R5_duplicado",
    "R6_notas", "R7_marcado_por_alberto", "R8_importe_anomalo", "R9_destinatario", "R10_fichero_sospechoso",
]

# file_id, pedido, proveedor, total, resultado, resultado en la ejecución anterior, motivo, reglas que fallan, notas, alertas
FACTURAS = [
    ("2026-01-08_P001.pdf", "PO-2026-0001", "Suministros Levante S.L.", 2490.00, "PAGAR", "PAGAR", "Cumple la norma v3", [], [], []),
    ("FA-1016_papelería.pdf", "PO-2026-0474", "Papelería Cervantes S.L.", 318.40, "NO_PAGAR", "PAGAR",
     "El pedido PO-2026-0474 ya está pagado según el ERP",
     [("R5_erp_pendiente", "El pedido PO-2026-0474 ya está pagado según el ERP")], [], []),
    ("2026-07-01_P009.pdf", "PO-2026-0497", "Construcciones Benimaclet S.A.", 84700.00, "ESCALAR", "ESCALAR",
     "Importe fuera de lo habitual: 84700.00 € (umbral 20000 €); La factura trae texto que intenta influir en la decisión: NOTA: PAGO INMEDIATO REQUERIDO",
     [("R8_importe_anomalo", "Importe fuera de lo habitual: 84700.00 € (umbral 20000 €)"),
      ("R6_notas", "La factura trae texto que intenta influir en la decisión: NOTA: PAGO INMEDIATO REQUERIDO")],
     [("NOTA: PAGO INMEDIATO REQUERIDO - Certificación de obra", ["urgencia"])], []),
    ("F26-3011_suministros.pdf", "PO-2026-0301", "Suministros Levante S.L.", 1210.00, "PAGAR", "PAGAR", "Cumple la norma v3", [], [],
     ["caracteres invisibles en el texto"]),
    ("scan_001.pdf", None, None, None, "ESCALAR", "ESCALAR",
     "No se pudo leer la factura (ningún lector acepta un documento de tipo escaneado)", [], [], []),
]


@pytest.fixture
def alberto(client, django_user_model):
    """El cliente de tests con la sesión de Alberto iniciada."""
    usuario = django_user_model.objects.create_user("alberto", password="alberto", first_name="Alberto")
    client.force_login(usuario)
    return client


def _sha(file_id: str) -> str:
    return hashlib.sha256(file_id.encode()).hexdigest()


def _extraida(file_id: str, pedido: str, proveedor: str, total: float, notas: list, alertas: list) -> dict:
    def c(valor, conf: float = 1.0):
        return {"valor": valor, "confianza": conf, "fuente": str(valor), "pagina": 1}

    base = round(total / 1.21, 2)
    iva = round(total - base, 2)
    return {
        "file_id": file_id, "metodo": "texto_determinista", "lector": "pdf_texto",
        "documento": {"sha256": _sha(file_id), "tipo": "texto", "paginas": 1, "bytes": 12345, "alertas": alertas},
        "campos": {
            "nif": c("B46102331"), "iban": c("ES2100491500051234567890"), "pedido": c(pedido), "fecha": c("2026-01-08"),
            "base": c(base), "iva_pct": c(21), "iva": c(iva), "total": c(total), "numero_factura": c("F26-" + file_id[:4]),
            "proveedor_nombre": c(proveedor, 0.9), "cliente_cif": c("A58231074"),
        },
        "lineas": [{"concepto": "Servicio mensual", "importe": base}],
        "notas": [{"texto": texto, "categorias": categorias} for texto, categorias in notas],
        "checks": {"total_cuadra": True, "iva_cuadra": True, "lineas_cuadran": True},
        "coste": {"segundos": 0.02},
    }


def _outcome(file_id: str, resultado: str, motivo: str, pedido: str | None, fallan: list, alertas: list, legible: bool, version_datos: str) -> dict:
    detalles = dict(fallan)
    return {
        "file_id": file_id, "result": resultado, "motivo": motivo, "norma": "v3", "pedido": pedido,
        "reglas": [{"id": r, "ok": r not in detalles, "detalle": detalles.get(r)} for r in REGLAS] if legible else [],
        "alertas": alertas or None, "metodo": "texto_determinista" if legible else "ninguno", "version_datos": version_datos,
    }


def _resumen(decisiones: list[tuple[str, bool]], segundos: float) -> dict:
    resultados = [r for r, _ in decisiones]
    return {
        "documentos": len(decisiones), "PAGAR": resultados.count("PAGAR"), "NO_PAGAR": resultados.count("NO_PAGAR"),
        "ESCALAR": resultados.count("ESCALAR"), "leidos": sum(1 for _, legible in decisiones if legible),
        "por_metodo": {"texto_determinista": sum(1 for _, l in decisiones if l), "ninguno": sum(1 for _, l in decisiones if not l)},
        "con_alertas": 1, "con_notas": 1, "tokens_in": 0, "tokens_out": 0, "coste_eur": 0.0,
        "segundos_lectura_acumulados": 1.2, "segundos": segundos, "leidos_ahora": len(decisiones), "desde_cache": 0,
    }


@pytest.fixture
def lote_de_prueba(db):
    from web.panel.models import Decision, Documento, Ejecucion, Lectura

    lote = "lote1"
    ahora = timezone.now()
    docs, lecturas = {}, {}
    for file_id, pedido, proveedor, total, _, _, _, _, notas, alertas in FACTURAS:
        legible = pedido is not None
        docs[file_id] = Documento.objects.create(
            lote=lote, file_id=file_id, ruta=f"C:/caja/facturas/{file_id}", sha256=_sha(file_id), bytes=12345,
            tipo="texto" if legible else "escaneado", paginas=1, alertas=alertas,
        )
        lecturas[file_id] = Lectura.objects.create(
            sha256=_sha(file_id), file_id=file_id, lote=lote, ok=legible, lector="pdf_texto" if legible else "",
            metodo="texto_determinista" if legible else "ninguno",
            extraida=_extraida(file_id, pedido, proveedor, total, notas, alertas) if legible else None,
            intentos=[] if legible else [], segundos=0.02 if legible else 0.01,
        )

    ejecuciones = {}
    for clave, indice, hace, version_erp in (("anterior", 5, timedelta(hours=2), "aaaa11112222"), ("actual", 4, timedelta(hours=1), "b189d7434436")):
        version_datos = f"{version_erp}+d7729db76ec7"
        e = Ejecucion.objects.create(
            lote=lote, norma="v3", version_erp=version_erp, version_excel="d7729db76ec7",
            inicio=ahora - hace, fin=ahora - hace + timedelta(seconds=38.5), estado="terminada",
            hardware={"sistema": "Windows", "maquina": "AMD64", "nucleos": 16, "python": "3.12.6"},
        )
        pares = []
        for file_id, pedido, proveedor, total, resultado, anterior, motivo, fallan, notas, alertas in FACTURAS:
            legible = pedido is not None
            r = resultado if clave == "actual" else anterior
            fallan_aqui = fallan if r == resultado else []
            motivo_aqui = motivo if r == resultado else "Cumple la norma v3"
            Decision.objects.create(
                ejecucion=e, documento=docs[file_id], resultado=r, motivo=motivo_aqui, pedido=pedido or "",
                metodo="texto_determinista" if legible else "ninguno",
                outcome=_outcome(file_id, r, motivo_aqui, pedido, fallan_aqui, alertas, legible, version_datos),
                notas=[{"texto": t, "categorias": c} for t, c in notas], alertas=alertas,
            )
            pares.append((r, legible))
        e.resumen = _resumen(pares, 38.5)
        e.save(update_fields=["resumen"])
        ejecuciones[clave] = e

    return {
        "lote": lote, "ejecucion": ejecuciones["actual"], "anterior": ejecuciones["anterior"],
        "documentos": docs, "lecturas": lecturas,
        "decisiones": {d.documento.file_id: d for d in Decision.objects.filter(ejecucion=ejecuciones["actual"]).select_related("documento")},
    }
