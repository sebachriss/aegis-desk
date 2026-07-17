# Evals — Agent Instructions

This directory contains the evaluation suite for Aegis Desk.

- `run_evals.py` runs cases from `datasets/test_cases.json` through the graph and computes scores.
- `judges.py` implements LLM-as-judge and RAG metrics.
- `rag_evals.py` runs retrieval-specific metrics.
- Results are saved to `evals/results/`.

## Conventions

- Keep test cases deterministic and self-contained.
- Every case should include `query`, `role`, `expected_intencion`, and `expected_contiene` (or the fields consumed by `judges.py`).
- Use `role: "empleado"` unless the case specifically tests admin behavior.
- Do not store API keys, secrets, or real PII in the dataset.
- RAG cases should work with both Supabase pgvector and Chroma fallback.

## Before committing

```bash
python -m evals.run_evals --save
```

If the pass rate drops, use the `.devin/workflows/fix-eval-regression.md` workflow.
