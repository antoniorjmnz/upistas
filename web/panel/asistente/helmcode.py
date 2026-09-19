"""El LLM de verdad: Helmcode (API compatible con OpenAI). Solo elige herramientas y redacta."""
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

    if not settings.helmcode_api_key:
        raise SinCliente("falta HELMCODE_API_KEY en el .env (se pide al equipo por privado)")
    cliente = _cliente(settings.helmcode_api_key, settings.helmcode_base_url)
    r = cliente.chat.completions.create(
        model=settings.modelo_texto,
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
    )
