"""Herramientas de solo lectura que el asistente puede usar para responder a Alberto.

El modelo elige cuál llamar y con qué argumentos; nosotros ejecutamos la consulta sobre
nuestra base de datos y le devolvemos el resultado. El modelo nunca escribe ni toca el ERP.
"""
from __future__ import annotations

import json

from web.panel import consultas

# Formato OpenAI tool-calling (Helmcode es compatible con la API de OpenAI).
HERRAMIENTAS = [
    {
        "type": "function",
        "function": {
            "name": "resumen_lote",
            "description": "Cuántas facturas hay para pagar, no pagar y revisar en el último lote procesado, y cuánto dinero suman las que se pagan.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_facturas",
            "description": "Busca facturas por nombre de fichero, número de factura (FA-…), pedido (PO-…), NIF o nombre del proveedor.",
            "parameters": {
                "type": "object",
                "properties": {"texto": {"type": "string", "description": "Lo que busca Alberto, tal cual"}},
                "required": ["texto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detalle_factura",
            "description": "Todo lo que se sabe de una factura concreta: qué se leyó del PDF, qué reglas se aplicaron y por qué se decidió así. Úsala para preguntas tipo «¿por qué no se paga esta?».",
            "parameters": {
                "type": "object",
                "properties": {"file_id": {"type": "string", "description": "Nombre del fichero, p.ej. 2026-01-08_P001.pdf"}},
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pendientes_revision",
            "description": "Facturas que el sistema ha escalado para que las mire una persona y que nadie ha revisado todavía.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_pedido",
            "description": "Qué dice la copia del ERP sobre un pedido: si está pagado o pendiente, importe y proveedor. Acepta «PO-2026-0474», «474»…",
            "parameters": {
                "type": "object",
                "properties": {"pedido": {"type": "string", "description": "Número de pedido"}},
                "required": ["pedido"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cambios_erp",
            "description": "Qué ha cambiado en el ERP entre la copia en uso y la anterior: asientos nuevos, modificados, eliminados y pedidos afectados. Para «¿qué ha cambiado desde la última vez?».",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_sincronizacion",
            "description": "Cuándo fue la última conexión con el ERP, si fue bien y qué versión de los datos se está usando.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

_FUNCIONES = {
    "resumen_lote": lambda: consultas.resumen_lote(),
    "buscar_facturas": lambda texto="": consultas.buscar_facturas(texto),
    "detalle_factura": lambda file_id="": consultas.detalle_factura(file_id),
    "pendientes_revision": lambda: consultas.pendientes_revision(),
    "estado_pedido": lambda pedido="": consultas.estado_pedido(pedido),
    "cambios_erp": lambda: consultas.cambios_erp(),
    "estado_sincronizacion": lambda: consultas.estado_sincronizacion(),
}


def ejecutar(nombre: str, argumentos: str | dict) -> dict:
    """Ejecuta una herramienta pedida por el modelo. Siempre devuelve algo legible, nunca explota."""
    funcion = _FUNCIONES.get(nombre)
    if funcion is None:
        return {"error": f"la herramienta «{nombre}» no existe"}
    try:
        args = json.loads(argumentos) if isinstance(argumentos, str) else dict(argumentos or {})
    except (TypeError, ValueError):
        return {"error": f"argumentos inválidos para «{nombre}»: {argumentos!r}"}
    try:
        datos = funcion(**args)
    except TypeError:
        return {"error": f"«{nombre}» no acepta esos argumentos: {sorted(args)}"}
    except Exception as e:  # una consulta rota no debe tumbar la conversación
        return {"error": f"la consulta «{nombre}» falló: {e}"}
    return {"datos": datos}
