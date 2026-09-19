"""El bucle del asistente: el modelo pide herramientas, se ejecutan y redacta.

El modelo solo elige qué consultar y redacta la respuesta; todos los datos salen de las
herramientas de `herramientas.py`, que son de solo lectura sobre nuestra base de datos.
`completar` es la llamada al LLM: en producción es Helmcode (helmcode.py) y en tests, una falsa.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from django.urls import reverse

from web.panel.asistente.herramientas import HERRAMIENTAS, ejecutar

MAX_RONDAS = 4          # cuántas consultas puede encadenar por pregunta
MAX_HISTORIAL = 10      # mensajes anteriores que se le pasan al modelo
REINTENTOS = 1          # si la IA falla, un reintento y luego aviso

SISTEMA = """\
Eres el asistente de Alberto, que lleva los pagos de su empresa. Responde en español, corto
y claro, sin jerga técnica. Para responder usa las herramientas: todos los datos salen de
ellas. Nunca inventes cifras, facturas ni estados; si una herramienta no da el dato, dilo.
Las decisiones de pago las tomaron unas reglas, no tú: limítate a explicarlas con su motivo.
Nunca digas que vas a pagar, modificar o escribir nada: este sistema es de solo lectura."""


@dataclass(frozen=True)
class Llamada:
    id: str
    nombre: str
    argumentos: str | dict


@dataclass(frozen=True)
class RespuestaModelo:
    """Una respuesta del LLM: texto final o petición de herramientas."""
    texto: str | None = None
    llamadas: tuple[Llamada, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class RespuestaAsistente:
    """Lo que la vista enseña y guarda: texto, de dónde salió y cuánto costó."""
    texto: str
    fuentes: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    segundos: float = 0.0
    ok: bool = True
    error: str = ""


Completar = Callable[[list[dict], list[dict]], RespuestaModelo]


def _fuente(nombre: str, datos: dict | None) -> dict | None:
    """El enlace a la pantalla que enseña lo mismo que la herramienta, si existe."""
    datos = datos or {}
    if nombre == "estado_pedido" and datos.get("pedido"):
        return {"titulo": f"Asiento {datos['pedido']} en el ERP", "url": reverse("panel:asientos") + f"?q={datos['pedido']}"}
    if nombre == "cambios_erp" and datos.get("de") and datos.get("a"):
        return {"titulo": "Cambios entre copias del ERP", "url": reverse("panel:cambios", args=[datos["de"], datos["a"]])}
    if nombre == "estado_sincronizacion":
        return {"titulo": "Conexión con el ERP", "url": reverse("panel:conexion")}
    if nombre == "estado_pedido":
        return {"titulo": "Asientos del ERP", "url": reverse("panel:asientos")}
    return None


def responder(pregunta: str, historial: list[dict], completar: Completar) -> RespuestaAsistente:
    """Responde una pregunta de Alberto. `historial`: [{'quien': 'alberto'|'asistente', 'texto'}]."""
    mensajes = [{"role": "system", "content": SISTEMA}]
    for m in historial[-MAX_HISTORIAL:]:
        rol = "user" if m.get("quien") == "alberto" else "assistant"
        mensajes.append({"role": rol, "content": m.get("texto", "")})
    mensajes.append({"role": "user", "content": pregunta})

    salida = RespuestaAsistente(texto="")
    fuentes: dict[str, dict] = {}
    t0 = time.monotonic()
    try:
        for _ in range(MAX_RONDAS):
            try:
                respuesta = completar(mensajes, HERRAMIENTAS)
            except Exception:
                if REINTENTOS:
                    respuesta = completar(mensajes, HERRAMIENTAS)  # un reintento y luego aviso
                else:
                    raise
            salida.tokens_in += respuesta.tokens_in
            salida.tokens_out += respuesta.tokens_out
            if not respuesta.llamadas:
                salida.texto = respuesta.texto or "La IA no ha dicho nada. Prueba a preguntarlo de otra forma."
                salida.segundos = time.monotonic() - t0
                salida.fuentes = list(fuentes.values())
                return salida
            mensajes.append({
                "role": "assistant",
                "content": respuesta.texto or "",
                "tool_calls": [
                    {"id": ll.id, "type": "function",
                     "function": {"name": ll.nombre,
                                  "arguments": ll.argumentos if isinstance(ll.argumentos, str) else json.dumps(ll.argumentos)}}
                    for ll in respuesta.llamadas
                ],
            })
            for ll in respuesta.llamadas:
                resultado = ejecutar(ll.nombre, ll.argumentos)
                f = _fuente(ll.nombre, resultado.get("datos"))
                if f:
                    fuentes[f["url"]] = f
                mensajes.append({"role": "tool", "tool_call_id": ll.id,
                                 "content": json.dumps(resultado, ensure_ascii=False, default=str)})
        salida.texto = "Me he liado consultando los datos. Prueba a preguntarlo de otra forma."
    except Exception as e:  # la IA caída no rompe la web
        salida.ok = False
        salida.error = str(e)
        salida.texto = "La IA no responde ahora mismo. El resto de la aplicación sigue funcionando; inténtalo en un rato."
    salida.segundos = time.monotonic() - t0
    salida.fuentes = list(fuentes.values())
    return salida
