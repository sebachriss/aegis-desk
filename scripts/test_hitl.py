"""Script de prueba: HITL (Human-in-the-Loop) con interrupt.

Demuestra:
1. Una acción (crear ticket) pasa por HITL → el humano aprueba
2. Una acción pasa por HITL → el humano rechaza
3. Una pregunta RAG no pasa por HITL (no es sensible)

HITL usa interrupt() de LangGraph que pausa el grafo.
Para reanudar, usamos Command(resume="approve"|"reject").
Necesitamos un checkpointer (MemorySaver) para guardar el estado al pausar.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agents.graph import build_graph


def main():
    # HITL requiere checkpointer para guardar estado al pausar
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    # --- Test 1: Acción aprobada por humano ---
    print(f"\n{'=' * 60}")
    print("TEST 1: Crear ticket — humano APRUEBA")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # Primera invocación — el grafo se pausa en hitl_node (interrupt)
    print("\n  Iniciando grafo (se pausará en HITL)...")
    result = graph.invoke({
        "messages": [],
        "query": "Crea un ticket de alta prioridad para el servidor caido",
        "user_id": "test_user",
        "role": "admin",
        "intencion": "",
        "respuesta": "",
        "fuentes": [],
        "confidence": 0.0,
        "requires_human_review": False,
        "retries": 0,
    }, config=config)

    # El grafo se pausó — revisar el estado
    # __interrupt__ contiene la info que interrupt() envió
    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        print(f"\n  ⏸️  GRAFO PAUSADO — esperando aprobación humana")
        print(f"  Resumen enviado al revisor:")
        # interrupt_info es una tupla de Interrupt objects
        for item in interrupt_info:
            print(f"  {item.value[:200]}")

        # Simular aprobación del humano
        print(f"\n  ✅ Humano aprueba...")
        result = graph.invoke(Command(resume="approve"), config=config)
    else:
        print("  (No se pausó — el flujo terminó sin HITL)")

    print(f"\n  Respuesta final: {result.get('respuesta', 'N/A')[:150]}")

    # --- Test 2: Acción rechazada por humano ---
    print(f"\n{'=' * 60}")
    print("TEST 2: Crear ticket — humano RECHAZA")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n  Iniciando grafo (se pausará en HITL)...")
    result = graph.invoke({
        "messages": [],
        "query": "Crea un ticket de baja prioridad para monitor roto",
        "user_id": "test_user",
        "role": "admin",
        "intencion": "",
        "respuesta": "",
        "fuentes": [],
        "confidence": 0.0,
        "requires_human_review": False,
        "retries": 0,
    }, config=config)

    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        print(f"\n  ⏸️  GRAFO PAUSADO — esperando aprobación humana")

        # Simular rechazo del humano
        print(f"\n  ❌ Humano rechaza...")
        result = graph.invoke(Command(resume="reject"), config=config)
    else:
        print("  (No se pausó — el flujo terminó sin HITL)")

    print(f"\n  Respuesta final: {result.get('respuesta', 'N/A')[:150]}")

    # --- Test 3: Pregunta RAG — no pasa por HITL ---
    print(f"\n{'=' * 60}")
    print("TEST 3: Pregunta RAG — NO requiere HITL")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n  Iniciando grafo (no debería pausarse)...")
    result = graph.invoke({
        "messages": [],
        "query": "¿Cuantos dias de vacaciones tengo?",
        "user_id": "test_user",
        "role": "empleado",
        "intencion": "",
        "respuesta": "",
        "fuentes": [],
        "confidence": 0.0,
        "requires_human_review": False,
        "retries": 0,
    }, config=config)

    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        print(f"\n  ⚠️  Se pausó inesperadamente (no debería para RAG)")
    else:
        print(f"\n  ✅ No se pausó — respuesta directa")

    print(f"  Respuesta final: {result.get('respuesta', 'N/A')[:150]}")


if __name__ == "__main__":
    main()
