"""Metricas por llamada al LLM: tokens, costo, latencia, tok/s.

Precios de DeepInfra DeepSeek-V4-Flash (por 1M tokens):
  - Input:  $0.09
  - Output: $0.18
  - Cached: $0.018
"""

import time

# Precios por 1 millon de tokens
PRECIO_INPUT = 0.09
PRECIO_OUTPUT = 0.18


def track_llm_call(
    usage: dict | None,
    elapsed_seconds: float,
) -> dict:
    """Calcula metricas a partir del usage_metadata y el tiempo medido.

    Args:
        usage: Diccionario usage_metadata de LangChain (input_tokens, output_tokens, etc).
            Puede ser None si el LLM no devolvio metadata.
        elapsed_seconds: Tiempo que tardo la llamada (medido externamente con time.time()).

    Returns:
        Diccionario con: input_tokens, output_tokens, total_tokens,
        costo_input, costo_output, costo_total, latencia_s, tok_por_segundo.
    """
    # 1. Extraer tokens del usage_metadata que devuelve LangChain
    usage = usage or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)

    # 2. Calcular costo
    #    Precio * (tokens / 1_000_000) = costo en dolares
    costo_input = (input_tokens / 1_000_000) * PRECIO_INPUT
    costo_output = (output_tokens / 1_000_000) * PRECIO_OUTPUT
    costo_total = costo_input + costo_output

    # 3. Calcular tokens por segundo (velocidad de generacion)
    #    Si la llamada tardo 0 segundos (imposible pero por seguridad), evitar division por cero
    tok_por_segundo = output_tokens / elapsed_seconds if elapsed_seconds > 0 else 0

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "costo_input": costo_input,
        "costo_output": costo_output,
        "costo_total": costo_total,
        "latencia_s": round(elapsed_seconds, 3),
        "tok_por_segundo": round(tok_por_segundo, 1),
    }


def print_metrics(metrics: dict) -> None:
    """Imprime las metricas en formato legible."""
    print(f"  Tokens:   {metrics['input_tokens']} in / {metrics['output_tokens']} out / {metrics['total_tokens']} total")
    print(f"  Costo:    ${metrics['costo_total']:.6f} (${metrics['costo_input']:.6f} in + ${metrics['costo_output']:.6f} out)")
    print(f"  Latencia: {metrics['latencia_s']}s")
    print(f"  Velocidad: {metrics['tok_por_segundo']} tok/s")
