"""El LLM de verdad: un proveedor compatible con OpenAI. Solo elige herramientas y redacta.

Por defecto es Helmcode (la misma clave que el pipeline); con ASISTENTE_BASE_URL, ASISTENTE_API_KEY y
ASISTENTE_MODELO en el .env el asistente va con otro (OpenRouter, por ejemplo) sin tocar nada más.
"""
from __future__ import annotations

from functools import cache

from web.panel.asistente.agente import Llamada, RespuestaModelo, SinCliente

TIMEOUT_SEGUNDOS = 40  # las respuestas reales tardan entre 13 y 36 s; con un solo reintento, el peor caso queda en minuto y medio

__all__ = ["SinCliente", "TIMEOUT_SEGUNDOS", "completar"]


@cache
def _cliente(api_key: str, base_url: str):
    from openai import OpenAI

    # Sin reintentos del SDK: los reintentos los decide agente.responder (uno), no la librería (dos más).
    return OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT_SEGUNDOS, max_retries=0)


def completar(mensajes: list[dict], herramientas: list[dict]) -> RespuestaModelo:
    """Una llamada al modelo de texto. Los fallos los gestiona agente.responder (reintento + aviso)."""
    from upistas.config import settings

    if not settings.asistente_api_key:
        raise SinCliente("falta ASISTENTE_API_KEY o HELMCODE_API_KEY en el .env (se pide al equipo por privado)")
    cliente = _cliente(settings.asistente_api_key, settings.asistente_base_url)
    r = cliente.chat.completions.create(
        model=settings.asistente_modelo,
        messages=mensajes,
        tools=herramientas,
        tool_choice="auto",
    )
    msg = r.choices[0].message
    llamadas = tuple(
        Llamada(tc.id, tc.function.name, tc.function.arguments or "{}")
        for tc in (msg.tool_calls or [])
    )
    uso = r.usage
    return RespuestaModelo(
        texto=msg.content,
        llamadas=llamadas,
        tokens_in=uso.prompt_tokens if uso else 0,
        tokens_out=uso.completion_tokens if uso else 0,
        modelo=getattr(r, "model", None) or settings.asistente_modelo,
    )
