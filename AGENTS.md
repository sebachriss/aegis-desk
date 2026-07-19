# Aegis Desk — Agent Instructions

Aegis Desk es una plataforma de soporte interno inteligente multi-agente en Python 3.11+ (backend FastAPI + LangGraph) y Next.js 16 (frontend). Este archivo guía a cualquier agente de IA (Devin, Cursor, Cascade, etc.) que trabaje en el repo.

## Propósito y arquitectura

```
Usuario
  │
  ▼
Security Node (prompt injection + rate limit + sanitize)
  │
  ▼
Supervisor (clasifica intención → enruta a worker)
  │        │           │           │
  ▼        ▼           ▼           ▼
RAG     Data       Action       Chat
(docs)  (SQL)      (tools)      (fallback)
  │        │           │
  └────────┴────┬──────┘
                ▼
            Crítico
                │
       ┌────────┴────────┐
       ▼                 ▼
 Respuesta OK        HITL (solo acciones sensibles)
```

- **Workers**: RAG Agent, Data Agent, Action Agent, Chat Agent.
- **Modelos**: DeepInfra `DeepSeek-V4-Flash` para workers; Groq `Llama-3.1-8B-Instant` / `Llama-3.3-70b` para supervisor y crítico.
- **RAG**: `sentence-transformers` local (`all-MiniLM-L6-v2`) + BM25 (`src/rag/lexical.py`) con RRF, más reranker cross-encoder (`src/rag/reranker.py`). Fallback a Chroma local. Flags `HYBRID_SEARCH_ENABLED` y `RERANKER_ENABLED` en `src/config.py`.
- **Datos**: **Supabase PostgreSQL** cuando `DATABASE_URL` está set; SQLite/Chroma como fallback local.
- **Checkpointer**: `langgraph-checkpoint-postgres` (`PostgresSaver`) con `psycopg[binary]`, con fallback a `langgraph-checkpoint-sqlite`.
- **HITL Queue**: persistida en PostgreSQL (`src/db/hitl_queue.py`) cuando `DATABASE_URL` está set, con fallback a SQLite.
- **Auth**: local bcrypt (`src/auth/users.py`) + opcional **Supabase Auth** para emails (`src/auth/supabase_auth.py`).
- **Frontend**: Next.js 16 + React 19 + shadcn/ui + Tailwind 4. Ver `frontend/AGENTS.md` para reglas específicas del frontend.

## Variables de entorno clave

Copiar `.env.example` a `.env` y completar:

- `DEEPINFRA_API_KEY` — obligatorio para workers.
- `GROQ_API_KEY` — opcional, recomendado para supervisor/crítico.
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY` — para Supabase Auth y operaciones admin.
- `DATABASE_URL` — conexión directa a Postgres (pooler de Supabase). Si el password tiene `$`, `@` o `%`, percent-encodearlos.
- `JWT_SECRET` — cambiar en producción.
- `CORS_ORIGINS` — restringir en producción.
- `LANGSMITH_*` — opcional, para tracing visual.

## Setup del entorno

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env con DEEPINFRA_API_KEY, GROQ_API_KEY y credenciales de Supabase

# Crear/migrar tablas en Supabase (o SQLite fallback)
PYTHONPATH=src python scripts/migrate_postgres.py

# Indexar documentos (usa Supabase pgvector si DATABASE_URL está set)
python -m src.rag.ingest
```

## Comandos de uso frecuente

| Comando | Propósito |
|---|---|
| `uvicorn src.api.main:app --port 8000` | Levantar API FastAPI |
| `make verify` | Verificación local rápida: tests + compile + frontend |
| `make full` | Verificación completa incluyendo evals/redteam |
| `make install-hooks` | Instala el pre-commit hook de Git |
| `.venv/bin/python -m pytest tests/ -q` | Tests deterministas (115 tests) |
| `.venv/bin/python -m evals.run_evals --save` | Suite de evaluaciones (37 casos) |
| `.venv/bin/python -m redteam.run_redteam --save` | Suite de red teaming (46 ataques) |
| `.venv/bin/python scripts/verify_all.py --full` | Script de verificación con baseline checks |
| `.venv/bin/python scripts/check_vector_store.py` | Reporta backend vectorial activo |
| `python scripts/cli_chat.py` | CLI interactivo para debug |
| `cd frontend && npm install && npm run dev` | Levantar frontend Next.js |
| `docker compose up -d` | Levantar API + UI + frontend con Docker |
| `PYTHONPATH=src python scripts/migrate_postgres.py` | Migrar tablas/checkpointer a Postgres |

## Estilo y convenciones

- Python 3.11+ con anotaciones de tipo (`typing`, `TypedDict` para `AgentState`).
- Cada módulo tiene docstring con propósito, estructura y ejemplos.
- Nombres en español para el dominio de negocio: `intencion`, `respuesta`, `fuentes`.
- Cada herramienta nueva en `src/tools/` se registra en `src/tools/registry.py`.
- Cada worker nuevo en `src/agents/` se conecta en `src/agents/supervisor.py` y `src/agents/graph.py`.

## Cómo añadir un worker

1. Crear `src/agents/<nombre>_agent.py` con función `<nombre>_node(state: AgentState) -> dict`.
2. Actualizar `src/agents/state.py` si necesitas nuevos campos de estado.
3. Añadir la intención/ruta en `src/agents/supervisor.py`.
4. Añadir nodo y edges en `src/agents/graph.py`.
5. Crear `scripts/test_<nombre>_agent.py`.
6. Añadir casos de eval en `evals/datasets/test_cases.json`.
7. Correr `python scripts/test_multi_agent.py`, `python -m evals.run_evals --save` y `python -m redteam.run_redteam --save`.

## Cómo añadir una herramienta

1. Crear función decorada con `@tool` en `src/tools/<nombre>.py`.
2. Si usa tablas nuevas, crearlas en `src/tools/sql.py` (SQLite), `scripts/migrate_postgres.py` (Postgres) y actualizar `ALLOWED_TABLES`.
3. Importarla en `src/tools/registry.py` y añadirla al diccionario `TOOLS`.
4. Actualizar `src/security/rbac.py` si tiene permisos especiales por rol.
5. Añadir tests y payloads de red teaming si expone nueva superficie de ataque.

## Seguridad y guardrails

- NO escribir secretos en código. Usar `src/config.py` + variables de entorno.
- SQL: solo `SELECT`. No permitir `INSERT`, `UPDATE`, `DELETE`, `DROP`.
- Email: solo dominios de la whitelist (`aegiscorp.com`, `aegis.com`).
- RBAC: `empleado` vs `admin`. Verificar `can_access(role, intencion)`.
- **Streaming (`/chat/stream`)**: usa las mismas guardas que `/chat` (auth, RBAC, rate limit en `security_node`, PII filter en la respuesta final). Utiliza `graph.astream(..., stream_mode=["updates","messages","values"])` con un `AsyncPostgresSaver` para tokens y HITL con Supabase. Los eventos SSE tipados son `node`, `token`, `interrupt`, `done`, `error`; no se streamean tokens del supervisor/crítico.
- **Supabase**: tablas tienen RLS habilitado; vector extension en schema `extensions`; service key solo en backend.
- Cualquier cambio en `src/security/` debe pasar `.venv/bin/python -m pytest tests/ -q` y `python -m redteam.run_redteam --save`.

## Evals, observabilidad y trazas

- `evals/run_evals.py`: 37 casos, guarda en `evals/results/`.
- `redteam/run_redteam.py`: 42 ataques, guarda en `redteam/results/`.
- Métricas en `src/observability/metrics.py` y trazas JSONL en `data/traces.jsonl`.

## Estado de verificación final

Tras el cierre de las fases de RAG avanzado (2026-07-19):

- `pytest tests/ -q` → 129 passed.
- `make retrieval-evals` → recall@1 85.71%, recall@3 100%, recall@5 100%, MRR 0.9226.
- `python -m evals.run_evals --save` → 37/37 (100%).
- `python -m redteam.run_redteam --save` → 46/46 (100%).
- `make verify` (tests + compile + frontend build) OK.

Ver detalles en `PROGRESS.md`.

## Reglas de debugging

- Si el grafo falla, revisar en orden: `src/agents/state.py` → nodo problemático → `src/agents/graph.py`.
- Si un eval falla, reproducir con `python scripts/cli_chat.py` o el script de fase correspondiente.
- Si hay brecha de seguridad, reproducir con `python -m redteam.run_redteam --category <categoria>`.
- Si falla conexión a Supabase, verificar `DATABASE_URL`, percent-encoding de caracteres especiales y pooler (Supavisor).
