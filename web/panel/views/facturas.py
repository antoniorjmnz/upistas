"""Las facturas del lote: la lista con su buscador, el detalle de cada una y el PDF original."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from web.panel import consultas
from web.panel.models import Decision, Documento, Lectura
from web.panel.templatetags.panel_extras import euros

POR_PAGINA = 25

# Lo que Alberto mira de una factura, en el orden en que lo mira. El IVA lleva su tipo y su cuota juntos.
LA_FACTURA = [
    ("proveedor_nombre", "Proveedor", ""),
    ("nif", "NIF", ""),
    ("iban", "Cuenta donde cobra", ""),
    ("pedido", "Pedido", ""),
    ("fecha", "Fecha", "fecha"),
    ("base", "Base imponible", "euros"),
    ("iva", "IVA", "euros"),
    ("total", "Total", "euros"),
    ("numero_factura", "Número de factura", ""),
]

# Todo lo que se leyó, con su nombre y cómo se escribe. Solo se enseña en el plegado técnico.
CAMPOS = [
    ("nif", "NIF del proveedor", ""),
    ("iban", "Cuenta donde cobra", ""),
    ("pedido", "Número de pedido", ""),
    ("fecha", "Fecha de la factura", "fecha"),
    ("base", "Base imponible", "euros"),
    ("iva_pct", "Tipo de IVA", "porcentaje"),
    ("iva", "IVA", "euros"),
    ("total", "Total", "euros"),
    ("numero_factura", "Número de factura", ""),
    ("proveedor_nombre", "Proveedor", ""),
    ("cliente_cif", "CIF de quien recibe la factura", ""),
]

# El texto de una factura nunca decide; se enseña y se explica de qué va.
CATEGORIAS = {
    "dirigida_al_sistema": "habla con el programa",
    "pide_saltar_regla": "pide saltarse una comprobación",
    "info_negocio": "afirma algo que solo usted puede confirmar",
    "urgencia": "mete prisa",
    "otra": "otro",
}

TIPO = {
    "texto": "PDF con texto",
    "escaneado": "Escaneado: es una foto, no tiene texto",
    "blanco": "En blanco",
    "roto": "Fichero dañado",
    "cifrado": "Protegido con contraseña",
    "otro": "Otro",
}

METODO = {
    "texto_determinista": "Leyendo el texto del PDF, sin inteligencia artificial",
    "ocr_determinista": "Reconociendo el texto del escaneado, sin inteligencia artificial",
    "texto_llm": "Con inteligencia artificial, sobre el texto del PDF",
    "vision_llm": "Con inteligencia artificial, mirando la imagen del escaneado",
    "ninguno": "No se pudo leer",
}

POCO_FIABLE = 0.8


def _fecha(valor) -> str:
    """'2026-01-08' → '08/01/2026'. Lo que no sea una fecha se deja tal cual."""
    if valor in (None, ""):
        return ""
    try:
        return date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except ValueError:
        return str(valor)


def lista(request: HttpRequest) -> HttpResponse:
    """Todas las facturas del lote, con lo que se decidió de cada una."""
    pedido_lote = (request.GET.get("lote") or "").strip()
    ejecucion = consultas.ultima_ejecucion(pedido_lote or None)
    q = (request.GET.get("q") or "").strip()
    resultado = request.GET.get("resultado") or ""

    decisiones = consultas.decisiones_de(ejecucion) if ejecucion else Decision.objects.none()
    cuenta = {f["resultado"]: f["n"] for f in decisiones.values("resultado").annotate(n=Count("id"))}
    revisiones = consultas.revisiones_por_documento(ejecucion.lote) if ejecucion else {}

    qs = decisiones.filter(resultado=resultado) if resultado else decisiones
    if q:
        # El proveedor no está en la decisión, sino dentro del JSON de la lectura.
        con_ese_proveedor = Lectura.objects.filter(extraida__campos__proveedor_nombre__valor__icontains=q).values("sha256")
        qs = qs.filter(
            Q(documento__file_id__icontains=q)
            | Q(pedido__icontains=q)
            | Q(motivo__icontains=q)
            | Q(documento__sha256__in=con_ese_proveedor)
        )

    pagina = Paginator(qs.order_by("documento__file_id"), POR_PAGINA).get_page(request.GET.get("pagina"))
    filas = list(pagina)
    lecturas = consultas.lecturas_por_sha([d.documento.sha256 for d in filas])
    for d in filas:
        datos = consultas.campos(lecturas.get(d.documento.sha256))
        d.proveedor = datos.get("proveedor_nombre")
        d.fecha = _fecha(datos.get("fecha"))
        d.total = datos.get("total")
        d.revision = revisiones.get(d.documento_id)
        d.porque = consultas.motivo_corto(d)

    ctx = {
        "lotes": consultas.lotes(),
        "lote": ejecucion.lote if ejecucion else pedido_lote,
        "ejecucion": ejecucion,
        "q": q,
        "resultado": resultado,
        "pagina": pagina,
        "cuenta": cuenta,
        "total": sum(cuenta.values()),
    }
    plantilla = "panel/_facturas_tabla.html" if request.headers.get("HX-Request") else "panel/facturas.html"
    return render(request, plantilla, ctx)


def _escrito(valor, formato: str) -> str:
    """El valor como lo escribiría Alberto: 84700.0 → '84.700,00 €', '2026-01-08' → '08/01/2026'."""
    if formato == "euros":
        return euros(valor)
    if formato == "porcentaje":
        return f"{valor} %"
    if formato == "fecha":
        return _fecha(valor)
    return str(valor)


def _poco_fiable(confianza) -> bool:
    """Si no estamos seguros de haber leído bien ese dato."""
    return isinstance(confianza, (int, float)) and not isinstance(confianza, bool) and confianza < POCO_FIABLE


def _la_factura(extraida: dict | None) -> list[dict]:
    """Los datos que Alberto mira, escritos como él los escribe. Valor vacío si el campo no aparece."""
    campos = (extraida or {}).get("campos") or {}
    filas = []
    for nombre, etiqueta, formato in LA_FACTURA:
        c = campos.get(nombre) or {}
        valor = c.get("valor")
        escrito = "" if valor in (None, "") else _escrito(valor, formato)
        if nombre == "iva" and escrito:
            tipo = (campos.get("iva_pct") or {}).get("valor")
            if tipo not in (None, ""):
                escrito = f"{tipo} % · {escrito}"
        filas.append({"etiqueta": etiqueta, "valor": escrito, "poco_fiable": _poco_fiable(c.get("confianza"))})
    return filas


def _leidos(extraida: dict | None) -> list[dict]:
    """Cada dato del contrato con su valor, lo seguros que estamos y en qué página estaba."""
    campos = (extraida or {}).get("campos") or {}
    filas = []
    for nombre, etiqueta, formato in CAMPOS:
        c = campos.get(nombre) or {}
        valor, conf = c.get("valor"), c.get("confianza")
        numerica = isinstance(conf, (int, float)) and not isinstance(conf, bool)
        falta = valor in (None, "")
        filas.append({
            "etiqueta": etiqueta,
            "valor": "" if falta else _escrito(valor, formato),
            "falta": falta,
            "confianza": round(conf * 100) if numerica else None,
            "pagina": c.get("pagina"),
            "poco_fiable": _poco_fiable(conf),
        })
    return filas


def detalle(request: HttpRequest, lote: str, file_id: str) -> HttpResponse:
    """Qué se decidió de una factura y por qué. Lo técnico va plegado."""
    ejecucion = consultas.ultima_ejecucion(lote)
    if ejecucion is None:
        raise Http404("Todavía no hemos decidido nada de este lote.")
    decision = get_object_or_404(
        Decision.objects.select_related("documento", "ejecucion"),
        ejecucion=ejecucion,
        documento__lote=lote,
        documento__file_id=file_id,
    )
    documento = decision.documento
    lectura = consultas.lecturas_por_sha([documento.sha256]).get(documento.sha256)
    extraida = lectura.extraida if lectura else None
    reglas = (decision.outcome or {}).get("reglas") or []
    revision = consultas.revisiones_por_documento(lote).get(documento.id)

    return render(request, "panel/factura.html", {
        "decision": decision,
        "documento": documento,
        "lectura": lectura,
        "ejecucion": ejecucion,
        "proveedor": consultas.campos(lectura).get("proveedor_nombre"),
        "motivo_corto": consultas.motivo_corto(decision),
        "reglas": reglas,
        "fallan": [r for r in reglas if not r.get("ok")],
        "datos": _la_factura(extraida),
        "leidos": _leidos(extraida),
        "notas": [
            {"texto": n.get("texto", ""), "categorias": [CATEGORIAS.get(c, c) for c in (n.get("categorias") or [])]}
            for n in (decision.notas or [])
        ],
        "alertas": list(dict.fromkeys((documento.alertas or []) + (decision.alertas or []))),
        "tipo": TIPO.get(documento.tipo, documento.tipo),
        "metodo": METODO.get(lectura.metodo, lectura.metodo) if lectura else METODO["ninguno"],
        "historial": Decision.objects.filter(documento=documento).select_related("ejecucion").order_by("ejecucion__inicio"),
        "revisiones": documento.revisiones.all(),
        "revision": revision,
        # Si el sistema no lo tiene claro, o si Alberto ya dijo la suya, lo primero es su decisión.
        "decidir_arriba": decision.resultado == "ESCALAR" or revision is not None,
    })


def pdf(request: HttpRequest, lote: str, file_id: str) -> HttpResponse:
    """El PDF original, tal cual llegó. La ruta sale de nuestra base de datos, no de la dirección."""
    documento = get_object_or_404(Documento, lote=lote, file_id=file_id)
    if not Path(documento.ruta).is_file():
        raise Http404(f"El PDF ya no está donde lo dejamos ({documento.ruta}). Vuelva a copiar la carpeta de facturas.")
    return FileResponse(open(documento.ruta, "rb"), content_type="application/pdf")
