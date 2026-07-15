"""Script de prueba: tracing de ejecuciones del grafo."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.graph import build_graph
from src.observability.tracing import load_traces, print_stats, trace_execution
from src.security.rate_limiter import reset_user


def main():
    print("\n=== Test de Tracing ===\n")

    graph = build_graph()

    preguntas = [
        ("¿Cuántos días de vacaciones tengo?", "empleado"),
        ("¿Cuántos empleados hay en total?", "admin"),
        ("Hola, ¿qué tal?", "empleado"),
    ]

    for query, role in preguntas:
        reset_user("trace_test")

        start = time.time()
        result = graph.invoke({
            "messages": [],
            "query": query,
            "user_id": "trace_test",
            "role": role,
            "intencion": "",
            "respuesta": "",
            "fuentes": [],
            "confidence": 0.0,
            "requires_human_review": False,
            "retries": 0,
        })
        elapsed = time.time() - start

        trace = trace_execution(
            query=query,
            intencion=result.get("intencion", ""),
            respuesta=result.get("respuesta", "")[:200],
            confidence=result.get("confidence", 0.0),
            fuentes=result.get("fuentes", []),
            retries=result.get("retries", 0),
            elapsed_seconds=elapsed,
            user_id="trace_test",
            role=role,
        )

        print(f"  [{trace['intencion']}] {query[:40]}... → {trace['elapsed_seconds']}s, conf={trace['confidence']}")

    # Mostrar traces cargados
    print(f"\n--- Traces recientes ---")
    traces = load_traces(limit=5)
    for t in traces:
        print(f"  {t['timestamp'][:19]} [{t['intencion']}] {t['query'][:40]}...")

    # Mostrar stats
    print_stats()


if __name__ == "__main__":
    main()
