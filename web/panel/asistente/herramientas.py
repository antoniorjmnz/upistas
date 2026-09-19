"""Herramientas que el asistente puede usar para responder a Alberto.

El modelo elige cuál llamar y con qué argumentos; nosotros ejecutamos la consulta sobre
nuestra base de datos y le devolvemos el resultado. Todas son de solo lectura menos
`proponer_accion`, que tampoco escribe: deja una propuesta que Alberto confirma o no
(acciones.py). El modelo nunca toca el ERP.

Las listas van acotadas (`limite`, hasta consultas.LIMITE_MAXIMO) y dicen `total` y `mas` (cuántas
quedan sin enseñar): así el modelo sabe cuándo ofrecer la pantalla filtrada con `ir_a`.
"""
from __future__ import annotations

import json

from web.panel import consultas
from web.panel.asistente import acciones, navegacion

_LIMITE = {
    "type": "integer",
    "description": f"Cuántas filas devolver como mucho (hasta {consultas.LIMITE_MAXIMO}). Súbelo si Alberto pide «todas», «las 40» o «enséñame más».",
}

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
            "description": (
                "Busca facturas por nombre de fichero, número de factura (FA-…), pedido (PO-…), NIF o nombre del proveedor. "
                "Devuelve las `limite` primeras (10 si no dices nada), `total` y `mas` (cuántas quedan)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"texto": {"type": "string", "description": "Lo que busca Alberto, tal cual"}, "limite": _LIMITE},
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
            "description": (
                "Facturas que el sistema ha escalado para que las mire una persona y que nadie ha revisado todavía. "
                "Devuelve las `limite` primeras (15 si no dices nada), `total` y `mas`."
            ),
            "parameters": {"type": "object", "properties": {"limite": _LIMITE}},
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
    {
        "type": "function",
        "function": {
            "name": "proveedor",
            "description": (
                "La ficha de un proveedor del maestro: nombre, código, NIF, cuenta (solo el final), días de pago, cuántos pedidos "
                "tiene y cuáles apuntó Alberto para revisar con qué nota. Acepta el código (P001), el NIF o el nombre."
            ),
            "parameters": {
                "type": "object",
                "properties": {"proveedor": {"type": "string", "description": "Código, NIF o nombre del proveedor"}},
                "required": ["proveedor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decisiones_de_alberto",
            "description": "Lo que Alberto decidió a mano sobre las facturas escaladas: cuál, si pagar o no, su comentario y cuándo. De la más reciente atrás.",
            "parameters": {
                "type": "object",
                "properties": {"lote": {"type": "string", "description": "Solo ese lote (lote1, lote2…); vacío para todos"}, "limite": _LIMITE},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repasos",
            "description": (
                "El registro de repasos: cada vez que se decidió un lote, cuándo, con qué norma, cuánto tardó, cuántas se pagan, "
                "no se pagan o escalan, y qué facturas cambiaron de resultado respecto al repaso anterior."
            ),
            "parameters": {"type": "object", "properties": {"limite": _LIMITE}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "importaciones",
            "description": "Las veces que Alberto importó proveedores o pedidos desde «Importar datos»: cuándo, qué fichero y cuántas filas nuevas, cambiadas o inválidas.",
            "parameters": {"type": "object", "properties": {"limite": _LIMITE}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explicar_regla",
            "description": (
                "Qué comprueba una regla de la norma, qué pasa si falla y por qué, en llano. Para «¿qué pasa si el IBAN es distinto?» "
                "o «¿por qué se revisan las que traen notas?» sin una factura delante. Acepta el id (R1_nif_iban), el número "
                "(«regla 1») o una palabra («iban», «pedido», «notas»). Sin argumento, la lista de reglas y el flujo entero."
            ),
            "parameters": {
                "type": "object",
                "properties": {"regla": {"type": "string", "description": "Id, número o palabra de la regla; vacío para verlas todas"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ir_a",
            "description": (
                "La dirección de una pantalla de esta web, para llevar a Alberto a ella (sale como botón «Ir a…»). "
                "Pantallas: inicio, facturas, revisar, factura, proveedores, proveedor, ejecuciones, erp, asientos, importar. "
                "facturas y revisar admiten filtros resultado/proveedor/desde/hasta/texto/lote; factura pide file_id; "
                "proveedor pide proveedor (código, NIF o nombre); asientos admite pedido. "
                "Úsala cuando una lista tiene más filas de las que has enseñado (`mas` > 0)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pantalla": {"type": "string", "enum": list(navegacion.PANTALLAS)},
                    "filtros": {
                        "type": "object",
                        "properties": {
                            "resultado": {"type": "string", "enum": ["PAGAR", "NO_PAGAR", "ESCALAR"]},
                            "proveedor": {"type": "string", "description": "Código P001, NIF o nombre del proveedor"},
                            "desde": {"type": "string", "description": "Fecha AAAA-MM-DD"},
                            "hasta": {"type": "string", "description": "Fecha AAAA-MM-DD"},
                            "texto": {"type": "string", "description": "Lo que se escribiría en el buscador"},
                            "file_id": {"type": "string", "description": "Nombre del fichero de la factura"},
                            "pedido": {"type": "string", "description": "Número de pedido (para asientos)"},
                            "lote": {"type": "string", "description": "lote1, lote2… (para facturas y revisar)"},
                        },
                    },
                },
                "required": ["pantalla"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proponer_accion",
            "description": (
                "Propone una acción para que Alberto la confirme con un botón; no la ejecuta. Solo estas: "
                "marcar_pedido_para_revisar {pedido}, quitar_marca_de_pedido {pedido}, "
                "apuntar_nota_en_pedido {pedido, nota}, apuntar_comentario_en_factura {file_id, comentario} "
                "(solo en facturas escaladas, sin decidirlas). Nada más: ni pagar, ni crear, ni borrar, ni el ERP."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": list(acciones.TIPOS)},
                    "datos": {
                        "type": "object",
                        "properties": {
                            "pedido": {"type": "string"},
                            "nota": {"type": "string"},
                            "file_id": {"type": "string"},
                            "comentario": {"type": "string"},
                        },
                    },
                },
                "required": ["tipo", "datos"],
            },
        },
    },
]

_FUNCIONES = {
    "resumen_lote": lambda: consultas.resumen_lote(),
    "buscar_facturas": lambda texto="", limite=10: consultas.buscar_facturas(texto, limite=limite),
    "detalle_factura": lambda file_id="": consultas.detalle_factura(file_id),
    "pendientes_revision": lambda limite=15: consultas.pendientes_revision(limite=limite),
    "estado_pedido": lambda pedido="": consultas.estado_pedido(pedido),
    "cambios_erp": lambda: consultas.cambios_erp(),
    "estado_sincronizacion": lambda: consultas.estado_sincronizacion(),
    "proveedor": lambda proveedor="": consultas.proveedor(proveedor),
    "decisiones_de_alberto": lambda lote="", limite=15: consultas.decisiones_de_alberto(lote or None, limite=limite),
    "repasos": lambda limite=10: consultas.repasos(limite=limite),
    "importaciones": lambda limite=10: consultas.importaciones(limite=limite),
    "explicar_regla": lambda regla="": consultas.explicar_regla(regla),
    "ir_a": lambda pantalla="", filtros=None: navegacion.ir_a(pantalla, filtros),
    "proponer_accion": lambda tipo="", datos=None: acciones.proponer(tipo, datos),
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
