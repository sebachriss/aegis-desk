"""Runner de evaluación de retrieval puro (sin LLM).

Mide recall@k (k=1,3,5) y MRR sobre el retriever configurado.
No requiere API keys: fuerza embeddings locales y Chroma/Supabase según
esté configurado, pero el resultado es determinista dado un vector store.

Uso:
    python -m evals.run_retrieval_evals           # corre y muestra tabla
    python -m evals.run_retrieval_evals --save    # guarda resultados
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Forzar modo local/determinista si no hay keys configuradas
os.environ.setdefault("DEEPINFRA_API_KEY", "")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.retriever import search

DATASET_PATH = Path(__file__).parent / "datasets" / "retrieval_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


def _get_git_commit() -> str:
    """Devuelve el hash corto del commit actual o 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def load_cases() -> list[dict]:
    """Carga los casos de evaluación de retrieval."""
    with open(DATASET_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


def _source_base(source: str) -> str:
    """Extrae el nombre del documento sin la sección ("doc.md § Sección")."""
    if not isinstance(source, str):
        return ""
    return source.split(" § ")[0].split("/")[-1]


def _source_matches(expected: str, result_source: str) -> bool:
    """Comprueba si un resultado satisface un expected_source.

    - expected="doc.md" coincide con cualquier "doc.md" o "doc.md § ...".
    - expected="doc.md § Sección" coincide si la base del documento es la misma.
      (la comparación de sección es insensible a mayúsculas y tildes).
    """
    result_base = _source_base(result_source)
    if " § " in expected:
        expected_base, expected_section = expected.split(" § ", 1)
        if _source_base(expected_base) != result_base:
            return False
        result_section = ""
        if " § " in result_source:
            result_section = result_source.split(" § ", 1)[1]
        return expected_section.lower() in result_section.lower()
    return _source_base(expected) == result_base


def _first_relevant_rank(results: list[dict], expected_sources: list[str]) -> int | None:
    """Devuelve el rank (1-based) del primer resultado relevante o None."""
    for rank, chunk in enumerate(results, start=1):
        source = chunk.get("source", "")
        if any(_source_matches(expected, source) for expected in expected_sources):
            return rank
    return None


def evaluate_case(case: dict) -> dict:
    """Ejecuta un caso de retrieval y calcula métricas."""
    query = case["query"]
    expected = case["expected_sources"]
    max_k = max(5, case.get("k", 5))

    start = time.perf_counter()
    results = search(query, k=max_k)
    elapsed_ms = (time.perf_counter() - start) * 1000

    top_sources = [chunk.get("source", "") for chunk in results[:5]]
    first_rank = _first_relevant_rank(results, expected)

    recalls = {}
    for k in (1, 3, 5):
        top_k = results[:k]
        recalls[f"recall@{k}"] = any(
            any(_source_matches(expected, chunk.get("source", "")) for expected in expected)
            for chunk in top_k
        )

    return {
        "id": case["id"],
        "query": query,
        "category": case.get("category", "unknown"),
        "expected_sources": expected,
        "top_sources": top_sources,
        "retrieval_scores": [round(float(chunk.get("score", 0.0)), 4) for chunk in results[:5]],
        "discarded": getattr(results, "discarded", 0),
        "first_relevant_rank": first_rank,
        "mrr": round(1.0 / first_rank, 4) if first_rank else 0.0,
        "recall@1": recalls["recall@1"],
        "recall@3": recalls["recall@3"],
        "recall@5": recalls["recall@5"],
        "latency_ms": round(elapsed_ms, 2),
    }


def _percent(values: list[bool]) -> float:
    return round(sum(1 for v in values if v) / len(values) * 100, 2) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def run_retrieval_evals(save: bool = False) -> dict:
    """Ejecuta todos los casos y genera el reporte."""
    cases = load_cases()
    results = []

    print("\n" + "=" * 80)
    print("  RETRIEVAL EVALS — baseline")
    print("=" * 80)
    print(f"\n  Casos: {len(cases)}\n")

    for case in cases:
        result = evaluate_case(case)
        results.append(result)
        print(
            f"  [{result['id']}] {result['query'][:45]:45s} "
            f"R@1={int(result['recall@1'])} R@3={int(result['recall@3'])} "
            f"R@5={int(result['recall@5'])} MRR={result['mrr']:.2f} "
            f"{result['latency_ms']:.1f}ms"
        )

    # Métricas agregadas
    recall1 = _percent([r["recall@1"] for r in results])
    recall3 = _percent([r["recall@3"] for r in results])
    recall5 = _percent([r["recall@5"] for r in results])
    mrr = round(sum(r["mrr"] for r in results) / len(results), 4) if results else 0.0
    latency_p50 = round(_median([r["latency_ms"] for r in results]), 2)

    by_category = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r)

    print("\n" + "=" * 80)
    print("  RESUMEN")
    print("=" * 80)
    print(f"  recall@1: {recall1:.2f}%")
    print(f"  recall@3: {recall3:.2f}%")
    print(f"  recall@5: {recall5:.2f}%")
    print(f"  MRR:      {mrr:.4f}")
    print(f"  Latencia p50: {latency_p50:.2f} ms")

    print("\n  Por categoría:")
    print(f"  {'Categoría':<12} {'Casos':>6} {'R@1':>7} {'R@3':>7} {'R@5':>7} {'MRR':>7}")
    print("  " + "-" * 48)
    for cat, rs in sorted(by_category.items()):
        print(
            f"  {cat:<12} {len(rs):>6} {_percent([r['recall@1'] for r in rs]):>6.2f}% "
            f"{_percent([r['recall@3'] for r in rs]):>6.2f}% "
            f"{_percent([r['recall@5'] for r in rs]):>6.2f}% "
            f"{round(sum(r['mrr'] for r in rs) / len(rs), 4):>7.4f}"
        )

    report = {
        "timestamp": datetime.now().isoformat(),
        "commit": _get_git_commit(),
        "total_cases": len(results),
        "recall@1": recall1,
        "recall@3": recall3,
        "recall@5": recall5,
        "mrr": mrr,
        "latency_p50_ms": latency_p50,
        "by_category": {
            cat: {
                "count": len(rs),
                "recall@1": _percent([r["recall@1"] for r in rs]),
                "recall@3": _percent([r["recall@3"] for r in rs]),
                "recall@5": _percent([r["recall@5"] for r in rs]),
                "mrr": round(sum(r["mrr"] for r in rs) / len(rs), 4),
            }
            for cat, rs in by_category.items()
        },
        "results": results,
    }

    if save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        commit = report["commit"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"retrieval_{timestamp}_{commit}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n  Guardado en: {out_path}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluación de retrieval")
    parser.add_argument("--save", action="store_true", help="Guarda resultados en evals/results/")
    args = parser.parse_args()

    run_retrieval_evals(save=args.save)


if __name__ == "__main__":
    main()
