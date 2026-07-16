"""Runner de evals: ejecuta la suite completa de test cases.

Para cada caso:
1. Ejecuta el grafo multi-agente con la pregunta
2. Evalúa la respuesta con LLM-as-judge
3. Para casos RAG: también evalúa con métricas RAG (faithfulness, relevance, precision)
4. Genera un reporte con scores por categoría y general

Uso:
    python -m evals.run_evals              # corre todo
    python -m evals.run_evals --category rag  # solo RAG
    python -m evals.run_evals --save       # guarda resultados en evals/results/
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from evals.judges import judge_response
from evals.rag_evals import evaluate_rag
from src.agents.graph import build_graph
from src.security.rate_limiter import reset_user

DATASET_PATH = Path(__file__).parent / "datasets" / "test_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


def load_test_cases(category: str | None = None) -> dict[str, list[dict]]:
    """Carga los test cases del dataset JSON.

    Args:
        category: Si se especifica, solo devuelve esa categoría.

    Returns:
        Dict con {categoria: [casos]}.
    """
    with open(DATASET_PATH) as f:
        data = json.load(f)

    if category and category in data:
        return {category: data[category]}

    return data


def run_single_case(graph, case: dict) -> dict:
    """Ejecuta un caso de test y lo evalúa.

    Args:
        graph: Grafo compilado de LangGraph (con checkpointer para HITL).
        case: Diccionario con el caso de test.

    Returns:
        Resultado con respuesta, score, métricas, y timing.
    """
    query = case["query"]
    role = case.get("role", "empleado")
    expected = case.get("expected_answer_contains")
    should_block = case.get("should_block", False)
    should_deny = case.get("should_deny", False)

    # Reset rate limiter para no interferir
    reset_user("eval_user")

    # Config con thread_id único para HITL
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # Ejecutar el grafo (puede pausarse en HITL)
    start_time = time.time()
    result = graph.invoke({
        "messages": [],
        "query": query,
        "user_id": "eval_user",
        "role": role,
        "intencion": "",
        "respuesta": "",
        "fuentes": [],
        "confidence": 0.0,
        "requires_human_review": False,
        "retries": 0,
    }, config=config)

    # Si el grafo se pausó en HITL, auto-aprobar para evals
    if result.get("__interrupt__"):
        result = graph.invoke(Command(resume="approve"), config=config)

    elapsed = time.time() - start_time

    respuesta = result.get("respuesta", "")
    intencion = result.get("intencion", "")
    fuentes = result.get("fuentes", [])
    confidence = result.get("confidence", 0.0)

    # Evaluar con LLM-as-judge
    judge_result = judge_response(
        query=query,
        response=respuesta,
        expected_contains=expected,
        should_block=should_block,
        should_deny=should_deny,
    )

    # Para casos RAG, evaluar también con métricas RAG
    rag_metrics = None
    if intencion == "rag" and fuentes:
        try:
            rag_metrics = evaluate_rag(query, respuesta, fuentes)
        except Exception as e:
            rag_metrics = {"error": str(e)}

    return {
        "id": case["id"],
        "query": query,
        "category": case.get("category", ""),
        "intencion": intencion,
        "respuesta": respuesta,
        "confidence": confidence,
        "judge_score": judge_result.score,
        "judge_categoria": judge_result.categoria,
        "judge_razon": judge_result.razon,
        "rag_metrics": rag_metrics,
        "elapsed_seconds": round(elapsed, 2),
        "expected_contains": expected,
        "should_block": should_block,
        "should_deny": should_deny,
    }


def run_evals(category: str | None = None, save: bool = False) -> dict:
    """Ejecuta la suite completa de evals.

    Args:
        category: Filtrar por categoría (None = todas).
        save: Si True, guarda resultados en evals/results/.

    Returns:
        Reporte completo con scores por categoría y general.
    """
    print("\n" + "=" * 60)
    print("  AEGIS DESK — EVAL SUITE")
    print("=" * 60)

    # Cargar casos
    cases_by_category = load_test_cases(category)
    total_cases = sum(len(cases) for cases in cases_by_category.values())
    print(f"\n  Total casos: {total_cases}")
    print(f"  Categorías: {', '.join(cases_by_category.keys())}")

    # Resetear base de datos para resultados deterministas
    from src.tools.sql import DB_PATH, _init_db
    if DB_PATH.exists():
        DB_PATH.unlink()
    _init_db()
    print("\n  Base de datos reiniciada para evals.")

    # Construir grafo con checkpointer (para HITL auto-aprobar)
    print("\n  Construyendo grafo...")
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    # Ejecutar cada caso
    results = []
    for cat, cases in cases_by_category.items():
        print(f"\n  --- Categoría: {cat} ({len(cases)} casos) ---")

        for case in cases:
            case["category"] = cat
            case_id = case["id"]

            print(f"    [{case_id}] {case['query'][:50]}...", end=" ")

            try:
                result = run_single_case(graph, case)
                results.append(result)

                score = result["judge_score"]
                categoria = result["judge_categoria"]
                elapsed = result["elapsed_seconds"]

                # Emoji según score
                if score >= 0.8:
                    emoji = "✅"
                elif score >= 0.5:
                    emoji = "⚠️"
                else:
                    emoji = "❌"

                print(f"{emoji} score={score:.2f} ({categoria}) [{elapsed}s]")

            except Exception as e:
                print(f"💥 ERROR: {e}")
                results.append({
                    "id": case_id,
                    "query": case["query"],
                    "category": cat,
                    "error": str(e),
                    "judge_score": 0.0,
                })

    # Calcular scores agregados
    report = generate_report(results, cases_by_category)

    # Mostrar reporte
    print_report(report)

    # Guardar si se pidió
    if save:
        save_results(report, results)

    return report


def generate_report(results: list[dict], cases_by_category: dict) -> dict:
    """Genera un reporte agregado a partir de los resultados."""
    categories = {}
    all_scores = []

    for result in results:
        cat = result.get("category", "unknown")
        score = result.get("judge_score", 0.0)

        if cat not in categories:
            categories[cat] = {"scores": [], "count": 0, "passed": 0, "failed": 0}

        categories[cat]["scores"].append(score)
        categories[cat]["count"] += 1

        if score >= 0.7:
            categories[cat]["passed"] += 1
        else:
            categories[cat]["failed"] += 1

        all_scores.append(score)

    # Calcular promedios
    for cat, data in categories.items():
        data["avg_score"] = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        data["pass_rate"] = data["passed"] / data["count"] if data["count"] else 0

    overall_avg = sum(all_scores) / len(all_scores) if all_scores else 0
    overall_pass = sum(1 for s in all_scores if s >= 0.7)
    overall_pass_rate = overall_pass / len(all_scores) if all_scores else 0

    # Métricas RAG agregadas (si hay)
    rag_scores = []
    for result in results:
        rag = result.get("rag_metrics")
        if rag and "error" not in rag:
            rag_scores.append(rag)

    rag_summary = None
    if rag_scores:
        rag_summary = {
            "avg_faithfulness": sum(r["faithfulness"] for r in rag_scores) / len(rag_scores),
            "avg_answer_relevance": sum(r["answer_relevance"] for r in rag_scores) / len(rag_scores),
            "avg_context_precision": sum(r["context_precision"] for r in rag_scores) / len(rag_scores),
            "count": len(rag_scores),
        }

    return {
        "timestamp": datetime.now().isoformat(),
        "total_cases": len(results),
        "overall_avg_score": round(overall_avg, 3),
        "overall_pass_rate": round(overall_pass_rate, 3),
        "overall_passed": overall_pass,
        "overall_failed": len(all_scores) - overall_pass,
        "categories": {cat: {
            "count": data["count"],
            "avg_score": round(data["avg_score"], 3),
            "pass_rate": round(data["pass_rate"], 3),
            "passed": data["passed"],
            "failed": data["failed"],
        } for cat, data in categories.items()},
        "rag_metrics": rag_summary,
    }


def print_report(report: dict) -> None:
    """Imprime el reporte en consola de forma legible."""
    print(f"\n{'=' * 60}")
    print("  REPORTE DE EVALS")
    print(f"{'=' * 60}")

    print(f"\n  Total casos: {report['total_cases']}")
    print(f"  Score promedio: {report['overall_avg_score']:.3f}")
    print(f"  Pass rate (>=0.7): {report['overall_pass_rate']:.1%} ({report['overall_passed']}/{report['total_cases']})")

    print(f"\n  Por categoría:")
    print(f"  {'Categoría':<15} {'Casos':>6} {'Avg':>8} {'Pass':>8} {'Pass%':>8}")
    print(f"  {'-'*15} {'-'*6} {'-'*8} {'-'*8} {'-'*8}")

    for cat, data in report["categories"].items():
        pass_str = f"{data['passed']}/{data['count']}"
        print(f"  {cat:<15} {data['count']:>6} {data['avg_score']:>8.3f} {pass_str:>8} {data['pass_rate']:>7.1%}")

    if report.get("rag_metrics"):
        rag = report["rag_metrics"]
        print(f"\n  Métricas RAG ({rag['count']} casos):")
        print(f"    Faithfulness:      {rag['avg_faithfulness']:.3f}")
        print(f"    Answer relevance:  {rag['avg_answer_relevance']:.3f}")
        print(f"    Context precision: {rag['avg_context_precision']:.3f}")

    # Veredicto
    if report["overall_pass_rate"] >= 0.9:
        print(f"\n  ✅ SUITE APROBADA (pass rate >= 90%)")
    elif report["overall_pass_rate"] >= 0.7:
        print(f"\n  ⚠️  SUITE APROBADA CON OBSERVACIONES (pass rate >= 70%)")
    else:
        print(f"\n  ❌ SUITE REPROBADA (pass rate < 70%) — revisar fallos")

    print(f"\n{'=' * 60}")


def save_results(report: dict, detailed_results: list[dict]) -> None:
    """Guarda el reporte y resultados detallados en JSON."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Reporte resumen
    report_path = RESULTS_DIR / f"report_{timestamp}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Reporte guardado: {report_path}")

    # Resultados detallados
    details_path = RESULTS_DIR / f"details_{timestamp}.json"
    with open(details_path, "w") as f:
        json.dump(detailed_results, f, indent=2, ensure_ascii=False)
    print(f"  Detalles guardados: {details_path}")


def main():
    parser = argparse.ArgumentParser(description="Ejecutar suite de evals de Aegis Desk")
    parser.add_argument("--category", type=str, default=None,
                        help="Filtrar por categoría: rag, datos, accion, chat, adversarial")
    parser.add_argument("--save", action="store_true",
                        help="Guardar resultados en evals/results/")
    args = parser.parse_args()

    run_evals(category=args.category, save=args.save)


if __name__ == "__main__":
    main()
