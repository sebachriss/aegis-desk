"""CLI de chat interactivo con streaming, memoria y metricas.

Comandos especiales:
  /salir     - Terminar la sesion
  /limpiar   - Vaciar la memoria de la conversacion
  /historial - Mostrar el historial guardado
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.providers import get_llm
from src.memory.short_term import ChatMemory
from src.observability.metrics import print_metrics, track_llm_call


def main():
    # 1. Inicializar todo
    llm = get_llm(streaming=True)
    memory = ChatMemory(max_messages=20)
    costo_total = 0.0

    print("=" * 50)
    print("  Aegis Desk - CLI de Chat")
    print(f"  Modelo: {llm.model_name}")
    print("  Comandos: /salir /limpiar /historial")
    print("=" * 50)
    print()

    # 2. Bucle principal
    while True:
        # input() bloquea hasta que el usuario presione Enter
        user_input = input("Tu: ").strip()

        # 3. Comandos especiales
        if not user_input:
            continue

        if user_input == "/salir":
            print(f"\nCosto total de la sesion: ${costo_total:.6f}")
            print("Hasta luego!")
            break

        if user_input == "/limpiar":
            memory.clear()
            print("[Memoria vaciada]\n")
            continue

        if user_input == "/historial":
            print(f"\n--- Historial ({len(memory.get_messages())} mensajes) ---")
            for msg in memory.get_messages():
                rol = type(msg).__name__
                print(f"  {rol}: {msg.content[:80]}")
            print("---\n")
            continue

        # 4. Guardar mensaje del usuario en memoria
        memory.add_user_message(user_input)

        # 5. Enviar al LLM con streaming
        print("LLM: ", end="", flush=True)

        inicio = time.time()

        # .stream() devuelve chunks. Recorremos e imprimimos en tiempo real.
        # Pero con streaming no tenemos usage_metadata en los chunks individuales.
        # El ultimo chunk si trae usage_metadata (LangChain lo acumula).
        respuesta_completa = ""
        usage = None

        for chunk in llm.stream(memory.get_messages()):
            print(chunk.content, end="", flush=True)
            respuesta_completa += chunk.content
            # El ultimo chunk tiene usage_metadata con los tokens totales
            if chunk.usage_metadata:
                usage = chunk.usage_metadata

        fin = time.time()
        elapsed = fin - inicio

        print()  # salto de linea despues del streaming

        # 6. Guardar respuesta del LLM en memoria
        memory.add_ai_message(respuesta_completa)

        # 7. Mostrar metricas
        metrics = track_llm_call(usage, elapsed)
        print_metrics(metrics)
        costo_total += metrics["costo_total"]
        print(f"  Costo sesion: ${costo_total:.6f}\n")


if __name__ == "__main__":
    main()
