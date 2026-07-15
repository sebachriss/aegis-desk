"""Script de prueba: agente ReAct con tool calling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.react_agent import run_agent


def main():
    preguntas = [
        "Crea un ticket de alta prioridad para el servidor caido",
        "Cuantos tickets abiertos hay?",
        "Cuantos empleados hay en la base de datos?",
        "Envia un email a rrhh@aegiscorp.com pidiendo informacion sobre el plan de carrera",
    ]

    for pregunta in preguntas:
        print(f"\n{'=' * 60}")
        print(f"Usuario: {pregunta}")
        print(f"{'=' * 60}")

        resultado = run_agent(pregunta)

        # Mostrar todos los pasos del agente (tools llamadas, etc.)
        print(f"\n--- Traza del agente ---")
        for msg in resultado["messages"]:
            tipo = type(msg).__name__
            if tipo == "HumanMessage":
                print(f"  [USER] {msg.content[:80]}")
            elif tipo == "AIMessage":
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        print(f"  [LLM] -> llama tool: {tc['name']}({tc['args']})")
                else:
                    print(f"  [LLM] {msg.content[:120]}")
            elif tipo == "ToolMessage":
                print(f"  [TOOL] {msg.content[:120]}")

        print(f"\n--- Respuesta final ---")
        print(f"  {resultado['response']}")


if __name__ == "__main__":
    main()
