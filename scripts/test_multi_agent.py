"""Script de prueba: sistema multi-agente con LangGraph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.graph import get_graph


def main():
    preguntas = [
        ("¿Cuantos dias de vacaciones tengo?", "rag"),
        ("Cuantos empleados hay en el departamento de Ventas?", "datos"),
        ("Crea un ticket de alta prioridad para el servidor caido", "accion"),
        ("Hola, que tal?", "chat"),
    ]
    roles = ["empleado", "admin", "empleado", "empleado"]

    graph = get_graph()

    for i, ((pregunta, expected), role) in enumerate(zip(preguntas, roles)):
        print(f"\n{'=' * 60}")
        print(f"Usuario: {pregunta}")
        print(f"Esperado: {expected}")
        print(f"{'=' * 60}")

        thread_id = f"test-multi-{i}"
        result = graph.invoke(
            {
                "messages": [],
                "query": pregunta,
                "user_id": "test_user",
                "role": role,
                "intencion": "",
                "respuesta": "",
                "fuentes": [],
                "confidence": 0.0,
                "requires_human_review": False,
                "retries": 0,
            },
            config={"configurable": {"thread_id": thread_id}},
        )

        print(f"\n  Intencion: {result['intencion']}")
        print(f"  Confidence: {result.get('confidence', 'N/A')}")
        print(f"  Reintentos: {result.get('retries', 0)}")
        print(f"  Requiere revision humana: {result.get('requires_human_review', False)}")

        if result.get("fuentes"):
            print(f"\n  Fuentes:")
            for f in result["fuentes"]:
                print(f"    - {f.get('source', 'desconocido')}")

        print(f"\n  Respuesta: {result['respuesta']}")

    # Visualizar el grafo
    print(f"\n{'=' * 60}")
    print("Estructura del grafo:")
    print(f"{'=' * 60}")
    try:
        mermaid = graph.get_graph().draw_mermaid()
        print(mermaid[:500])
    except Exception:
        print("  (No se pudo generar visualización Mermaid)")
        print("  Flujo: START → supervisor → [rag|data|action|chat] → critic → END")


if __name__ == "__main__":
    main()
