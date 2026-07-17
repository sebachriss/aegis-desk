# Aegis Desk

## Summary

Aegis Desk es una plataforma de soporte interno inteligente multi-agente (FastAPI + LangGraph + Next.js). Incluye RAG, Data Agent SQL, Action Agent con HITL, red teaming, evals y observabilidad.

## When to use

Usa esta skill cuando trabajes en el repositorio `aegis-desk` para recordar arquitectura, convenciones y comandos de verificación.

## Guidelines

- Lenguaje del dominio en español: `intencion`, `respuesta`, `fuentes`, `consultar_sql`, `crear_ticket`.
- Python 3.11+ con anotaciones de tipo; usa `TypedDict` para `AgentState`.
- Nunca escribas secretos en código; usá `src/config.py` + variables de entorno.
- Registrá nuevas tools en `src/tools/registry.py` y permisos en `src/security/rbac.py`.
- Cualquier cambio en seguridad debe reflejarse en `redteam/attacks/payloads.json` y pasar `make redteam`.
- Si `read`/`edit`/`write` devuelven `internal error`, usá `exec` con `cd aegis-desk` y scripts Python/`git`.

## Commands

| Comando | Propósito |
|---|---|
| `make verify` | Tests + compileall + frontend build |
| `make full` | Verify + evals + redteam |
| `make test` | `pytest tests/ -q` |
| `make evals` | Suite de evals (33 casos) |
| `make redteam` | Suite de red teaming (36 ataques) |
| `.venv/bin/python scripts/check_vector_store.py` | Reporta backend vectorial activo |
| `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/ -q` | Si `make test` no funciona |

## Verification baselines

- `pytest`: 82 passed.
- `evals`: 33/33 (100%).
- `redteam`: 36/36 (100%).
- Frontend: `npm run lint && npm run build` OK.

## Common pitfalls

- El retriever RAG prioriza: Pinecone > Supabase pgvector (`DATABASE_URL`) > Chroma local.
- `consultar_sql` es una función callable; `consultar_sql_tool` es el `StructuredTool` para agentes.
- HITL usa `interrupt()` de LangGraph; aprobación con `Command(resume={"decision": "approve", "approved_by": "..."})`.
- Los traces se guardan en `data/traces.jsonl` con PII redactada.
