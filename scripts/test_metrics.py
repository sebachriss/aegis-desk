"""Script de prueba: metricas de llamadas al LLM (tokens, costo, latencia, tok/s)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage

from src.llm.providers import get_llm
from src.observability.metrics import print_metrics, track_llm_call


def main():
    llm = get_llm()

    prompts = [
        "Hola, ¿quien eres?",
        "Explica que es RAG en 3 frases.",
        "Escribe una funcion Python que calcule el factorial de un numero.",
    ]

    total_costo = 0.0
    total_tokens = 0

    for i, prompt in enumerate(prompts, 1):
        print(f"\n--- Llamada {i} ---")
        print(f"  Prompt: {prompt[:50]}...")

        # 1. Medir tiempo ANTES de la llamada
        inicio = time.time()

        # 2. Hacer la llamada
        response = llm.invoke([HumanMessage(content=prompt)])

        # 3. Medir tiempo DESPUES
        fin = time.time()
        elapsed = fin - inicio

        # 4. Calcular metricas
        metrics = track_llm_call(response.usage_metadata, elapsed)

        # 5. Mostrar
        print(f"  Respuesta: {response.content[:60]}...")
        print_metrics(metrics)

        total_costo += metrics["costo_total"]
        total_tokens += metrics["total_tokens"]

    # Resumen total
    print("\n" + "=" * 40)
    print("RESUMEN TOTAL")
    print("=" * 40)
    print(f"  Tokens totales: {total_tokens}")
    print(f"  Costo total:    ${total_costo:.6f}")
    print(f"  Presupuesto:    $10.00")
    print(f"  Restante:       ${10.00 - total_costo:.6f}")


if __name__ == "__main__":
    main()
