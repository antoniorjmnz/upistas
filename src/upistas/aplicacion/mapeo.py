"""Traducción entre contratos (JSON en los bordes) y modelos de dominio."""
from __future__ import annotations

import re
from decimal import Decimal

from upistas.contracts.decision import Decision as DecisionContrato
from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.dominio.importes import normaliza_iban, pais_del_nif, parse_fecha
from upistas.dominio.modelos import Decision, Factura, Nota

# Por debajo de esta confianza un campo se trata como no leído (y las reglas lo verán como duda).
CONFIANZA_MINIMA = 0.8

CAMPOS = ("nif", "iban", "pedido", "fecha", "base", "iva_pct", "iva", "total", "numero_factura", "proveedor_nombre", "cliente_cif")


def a_factura(extraida: FacturaExtraida) -> Factura:
    c = extraida.campos
    valores: dict[str, object] = {}
    ausentes: set[str] = set()
    no_leidos: set[str] = set()
    for nombre in CAMPOS:
        campo = getattr(c, nombre, None)
        if campo is None or campo.valor is None:
            # valor null + confianza alta = seguro que no está; confianza baja = no se pudo leer
            (ausentes if campo is not None and campo.confianza >= CONFIANZA_MINIMA else no_leidos).add(nombre)
            valores[nombre] = None
        elif campo.confianza < CONFIANZA_MINIMA:
            no_leidos.add(nombre)
            valores[nombre] = None
        else:
            valores[nombre] = campo.valor

    # Leído por OCR o visión, un dato puede venir con un carácter cambiado (B→8, O→0): un NIF sin forma de NIF
    # no se da por leído, y la factura queda marcada `por_ocr` para que un dato que no cuadre no la rechace.
    metodo = str(getattr(extraida.metodo, "value", extraida.metodo) or "")
    por_ocr = metodo.startswith(("ocr", "vision"))
    if por_ocr and valores.get("nif") and pais_del_nif(str(valores["nif"])) == "??":
        no_leidos.add("nif")
        valores["nif"] = None

    def dec(nombre: str) -> Decimal | None:
        v = valores[nombre]
        return Decimal(str(v)) if v is not None else None

    # Lecturas anteriores al campo `divisa` no lo traen: sin dato, euros, como siempre.
    divisa = c.divisa.valor if c.divisa is not None and c.divisa.valor and c.divisa.confianza >= CONFIANZA_MINIMA else "EUR"
    # Una fecha leída con seguridad que no existe (31/02/2026): lo que pone, para decirlo en el motivo.
    fecha_texto = None
    if "fecha" in ausentes and getattr(c, "fecha", None) is not None and c.fecha.fuente:
        escrita = re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}", c.fecha.fuente)
        fecha_texto = escrita[0] if escrita else None

    return Factura(
        file_id=extraida.file_id,
        nif=valores["nif"],
        iban=normaliza_iban(valores["iban"]),
        pedido=valores["pedido"],
        fecha=parse_fecha(valores["fecha"] or "") if valores["fecha"] else None,
        base=dec("base"),
        iva_pct=dec("iva_pct"),
        iva=dec("iva"),
        total=dec("total"),
        divisa=divisa,
        por_ocr=por_ocr,
        lineas=tuple(Decimal(str(linea.importe)) for linea in (extraida.lineas or [])),
        numero=valores["numero_factura"],
        proveedor_nombre=valores["proveedor_nombre"],
        cliente_cif=valores["cliente_cif"],
        notas=tuple(Nota(n.texto, tuple(cat.value for cat in n.categorias)) for n in (extraida.notas or [])),
        alertas=tuple(extraida.documento.alertas or []),
        tipo_documento=extraida.documento.tipo.value,
        metodo=extraida.metodo.value,
        ausentes=frozenset(ausentes),
        no_leidos=frozenset(no_leidos),
        sha256=extraida.documento.sha256,
        errores_lectura=tuple(extraida.errores or []),
        fecha_texto=fecha_texto,
    )


def a_outcome(decision: Decision, version_datos: str = "", metodo: str | None = None) -> dict:
    """Una línea de outcomes.jsonl (valida contra contracts/decision.schema.json)."""
    contrato = DecisionContrato(
        file_id=decision.file_id,
        result=decision.resultado.value,
        motivo=decision.motivo,
        norma=decision.norma,
        pedido=decision.pedido,
        reglas=[{"id": c.regla, "ok": c.ok, "detalle": c.detalle or None} for c in decision.comprobaciones],
        alertas=list(decision.alertas) or None,
        metodo=metodo,
        version_datos=version_datos or None,
    )
    return contrato.model_dump(mode="json", exclude_none=True)
