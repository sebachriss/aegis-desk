"""Script de prueba: HITL (Human-in-the-Loop) con action_plan estructurado.

Demuestra Fase 2 (SEC-02):
1. Admin pide enviar email -> planner genera action_plan de riesgo 'high'
   -> grafo se pausa en hitl_node -> humano APRUEBA -> action_executor ejecuta.
2. Admin pide enviar email -> humano RECHAZA -> action_executor no corre.
3. Empleado pide crear ticket -> riesgo 'low' -> no pasa por HITL.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agents.graph import build_graph


def main():
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    # --- Test 1: Email aprobado por humano ---
    print(f"\n{'=' * 60}")
    print("TEST 1: Enviar email — humano APRUEBA")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n  Iniciando grafo (deberia pausarse en HITL)...")
    result = graph.invoke(
        {
            "messages": [],
            "query": "Envia un email a rrhh@aegiscorp.com con asunto 'Solicitud de aumento'",
            "user_id": "admin_test",
            "role": "admin",
            "intencion": "",
            "respuesta": "",
            "fuentes": [],
            "confidence": 0.0,
            "requires_human_review": False,
            "retries": 0,
        },
        config=config,
    )

    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        print("\n  ⏸️  GRAFO PAUSADO — esperando aprobacion humana")
        for item in interrupt_info:
            print(f"  {item.value[:250]}")

        print("\n  ✅ Humano aprueba...")
        result = graph.invoke(Command(resume="approve"), config=config)
    else:
        print("  (No se pauso — el flujo termino sin HITL)")

    print(f"\n  Respuesta final: {result.get('respuesta', 'N/A')[:150]}")
    print(f"  Estado ejecucion: {result.get('action_plan', {}).get('execution_status')}")

    # --- Test 2: Email rechazado por humano ---
    print(f"\n{'=' * 60}")
    print("TEST 2: Enviar email — humano RECHAZA")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n  Iniciando grafo (deberia pausarse en HITL)...")
    result = graph.invoke(
        {
            "messages": [],
            "query": "Envia un email a rrhh@aegiscorp.com con asunto 'Solicitud de aumento'",
            "user_id": "admin_test",
            "role": "admin",
            "intencion": "",
            "respuesta": "",
            "fuentes": [],
            "confidence": 0.0,
            "requires_human_review": False,
            "retries": 0,
        },
        config=config,
    )

    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        print("\n  ⏸️  GRAFO PAUSADO — esperando aprobacion humana")

        print("\n  ❌ Humano rechaza...")
        result = graph.invoke(Command(resume="reject"), config=config)
    else:
        print("  (No se pauso — el flujo termino sin HITL)")

    print(f"\n  Respuesta final: {result.get('respuesta', 'N/A')[:150]}")
    print(f"  Estado aprobacion: {result.get('action_plan', {}).get('approval_status')}")

    # --- Test 3: Crear ticket (low risk) no pasa por HITL ---
    print(f"\n{'=' * 60}")
    print("TEST 3: Crear ticket — NO requiere HITL")
    print(f"{'=' * 60}")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n  Iniciando grafo (no deberia pausarse)...")
    result = graph.invoke(
        {
            "messages": [],
            "query": "Crea un ticket de alta prioridad para el servidor caido",
            "user_id": "empleado_test",
            "role": "empleado",
            "intencion": "",
            "respuesta": "",
            "fuentes": [],
            "confidence": 0.0,
            "requires_human_review": False,
            "retries": 0,
        },
        config=config,
    )

    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        print("\n  ⚠️  Se pauso inesperadamente (no deberia para tickets)")
    else:
        print("\n  ✅ No se pauso — respuesta directa")

    print(f"  Respuesta final: {result.get('respuesta', 'N/A')[:150]}")


if __name__ == "__main__":
    main()
