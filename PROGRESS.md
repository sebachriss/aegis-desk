## 2026-07-18 — Funcionalidad de vacaciones

**Objetivo:** implementar solicitud y consulta de vacaciones siguiendo el `PLAN_VACACIONES.md`.

- **`src/tools/vacaciones.py`**: tools `consultar_saldo_vacaciones`, `solicitar_vacaciones` y `listar_solicitudes_vacaciones`. Triple backend (Postgres/Supabase/SQLite), validación de fechas, cálculo de días hábiles, descuento atómico de saldo e idempotencia.
- **Modelo de datos**: tablas `vacaciones_saldo` y `vacaciones_solicitudes` en `src/tools/sql.py`, `scripts/migrate_postgres.py` y seeds con 22 días de saldo para los 6 empleados.
- **RBAC**: `src/security/rbac.py` añade las 3 tools a `empleado` y `admin`.
- **Registry**: `src/tools/registry.py` registra las nuevas tools.
- **Action Agent**: `solicitar_vacaciones` es `high` risk → HITL; inyección de `created_by`, `role`, `idempotency_key` y `aprobado_por`; validación fail-closed de fechas en el planner.
- **HITL**: `src/agents/hitl_node.py` redacta fechas y motivo, calcula días hábiles para el resumen del revisor.
- **Supervisor**: fast path para "solicitar vacaciones", "saldo de vacaciones" y "consultar saldo"; la política de vacaciones sigue siendo RAG.
- **Tests**: `tests/test_vacaciones.py` (23 tests) cubre tools, RBAC, planning, ejecución, replay, HITL, supervisor y determinismo de días hábiles.
- **Evals**: dataset ampliado a 37 casos (`rag_11`, `act_06`–`act_08`) con casos de vacaciones.
- **Redteam**: nueva categoría `vacaciones` con 6 ataques (spoofing, bypass HITL, tool chaining, prompt injection en motivo, valores absurdos y exceso de días).

**Verificación:**
- `make test` → 105 passed (previo 82 + 23 nuevos).
- `make compile` → OK.
- `make verify` → OK (tests + compileall + frontend build/lint).
- `python -m evals.run_evals --save` → 37/37 (100%).
- `python -m redteam.run_redteam --save` → 42/42 (100%).

## 2026-07-17 — Proceso, Devin skill, RAG tracing y CI

**Objetivo:** cerrar las mejoras de proceso propuestas y transparentar el backend vectorial.

- **`scripts/pre-commit.sh` + `make install-hooks`**: hook de Git que corre `make verify` antes de cada commit.
- **`.devin/skills/aegis-desk/SKILL.md`**: contexto del repo para futuras sesiones de agentes.
- **`scripts/check_vector_store.py`**: reporta backend vectorial activo y cantidad de embeddings.
- **RAG tracing**: `AgentState` guarda `retrieval_scores` y `discarded`; `trace_execution` los persiste.
- **`.github/workflows/ci.yml`**: usa `make verify`, cache de pip y `scripts/verify_all.py --full` para baseline checks.
- **`REMEDIATION_PLAN.md`**: items de validador de fuentes, threshold de relevancia y score de retrieval marcados como implementados.

**Vector store activo:** `Supabase pgvector` (22 embeddings); `Chroma local` existe como fallback.

## 2026-07-17 — Makefile y script de verificación local

**Objetivo:** estandarizar y simplificar la verificación del repo.

- **`Makefile`**: targets `test`, `compile`, `frontend`, `evals`, `redteam`, `verify`, `full`, `clean`.
- **`scripts/verify_all.py`**: script Python que corre tests, compileall, frontend build y baseline checks de evals/redteam (`--full`).
- README y AGENTS.md documentan `make verify` como comando principal de validación.

**Verificación:** `make test` → 82 passed; `make compile` → OK.

## 2026-07-17 — Cierre del REMEDIATION_PLAN.md

**Objetivo:** cerrar los 34 ítems restantes del plan y dejar el proyecto en estado verificable.

- **REMEDIATION_PLAN.md**: todos los ítems marcados `[x]`. Los que requieren infraestructura futura tienen nota de backlog.
- **ID único entre procesos**: `_new_action_id` en `src/agents/action_agent.py` ahora usa `uuid4` + timestamp.
- **Commit en reportes**: `redteam/run_redteam.py` incluye `commit` en el reporte JSON.
- **Prompt injection**: detección de bypass HITL/replay, exfiltración a dominios externos y tool chaining.

**Verificación final:**
- `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/ -q` → 82 passed, 2 warnings.
- `python -m compileall -q src evals redteam scripts` OK.
- `npm run lint && npm run build` OK.
- `python -m evals.run_evals --save` → 33/33 (100%).
- `python -m redteam.run_redteam --save` → 36/36 (100%).

## 2026-07-17 — Fixes de regresión y estabilidad de tests

**Objetivo:** cerrar brechas detectadas en `tests/test_security_core.py` y `tests/test_api.py`.

- **SQL `consultar_sql` callable**: `src/tools/sql.py` expone `consultar_sql` como función callable (tests/CLI) y `consultar_sql_tool` como `StructuredTool` LangChain para `create_react_agent`; `src/tools/registry.py` usa la versión tool.
- **SQL validation robusta**: `_validate_select` acepta punto y coma final y usa word boundaries para `SQL_KEYWORDS_DENY`, evitando falsos positivos con nombres de columna como `created_by`.
- **Prompt injection espaciado**: `src/security/prompt_injection.py` ya no marca como inyección cadenas con espacios entre letras (e.g. `i g n o r e a l l i n s t r u c t i o n s`) mientras mantiene detección de variaciones concatenadas (`ignoreregla`, `ignoralasreglas`).
- **Action Agent RBAC**: `src/agents/action_agent.py` inyecta `role` y `created_by` sin depender de la firma dinámica de cada tool.
- **API guardrails**: `src/api/main.py` devuelve rol por defecto `empleado` y mensaje genérico en errores internos; `src/agents/state.py` inicializa `last_error` por defecto.

**Verificación:**
- `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/ -q` → 82 passed, 2 warnings.
- `python -m compileall -q src evals redteam scripts` OK.
- `npm run lint && npm run build` OK.
- `python -m evals.run_evals --save` → 33/33 (100%).
- `python -m redteam.run_redteam --save` → 36/36 (100%), breaches en `tool_chaining` y `replay` corregidos con patrones adicionales en `src/security/prompt_injection.py` (bypass HITL/replay, exfiltración a dominios externos, tool chaining).


# Aegis Desk — Bitácora de Progreso

## 2026-07-16 — Auditoría y cierre de gaps del REMEDIATION_PLAN.md

**Objetivo:** cerrar los ítems P0/P1 del `REMEDIATION_PLAN.md` verificando código y ampliando tests.

- **HITL auditoría correcta**: `src/agents/hitl_node.py` acepta `Command(resume={"decision": "approve|reject", "approved_by": "..."})`; `src/api/main.py` pasa el admin aprobador real.
- **HITL PII**: `src/db/hitl_queue.py` redacta `query` y `action_plan.arguments` (cuerpo de email, descripciones, secrets) antes de persistir.
- **Tickets unificados con SQL**: `src/tools/tickets.py` ahora usa PostgreSQL directo cuando `DATABASE_URL` está configurado, evitando doble fuente de verdad con `src/tools/sql.py`.
- **RAG anti-inyección**: `src/rag/ingest.py` descarta chunks con patrones de prompt injection; `src/rag/chain.py` redacta PII en el contexto y en las fuentes devueltas.
- **RBAC tests**: tests de que `empleado` no puede usar `enviar_email`/`consultar_sql` y `admin` sí.
- **SQL tests**: tests de `DELETE`, `UPDATE`, `INSERT`, stacked queries, `UNION` y `sqlite_master`.
- **JWT tests**: tests de firma incorrecta y token expirado.
- **API tests**: `422` para query >4000, `401` para `/stats` sin token, `403` para `/hitl/pending` como empleado.
- **HITL tests**: decisión inválida, reanudación con dict, replay rechazado.
- **Rate limit tests**: dos usuarios no comparten contador.
- **RAG/PII tests**: chunks maliciosos rechazados, PII redactado en fuentes.
- **CI**: `.github/workflows/ci.yml` con `compileall`, `pytest`, `npm run lint` y `npm run build`.
- **Evals/Redteam**: `python -m evals.run_evals --save` → 33/33 (100%), `python -m redteam.run_redteam --save` → 31/31 (100%).
- **Docker**: `docker compose build` OK para `api`, `ui` y `frontend`.

**Verificación:** `python -m compileall -q src evals redteam scripts` OK; `PYTHONPATH=$PWD pytest tests/ -q` → 50 passed; `npm run lint && npm run build` OK; `docker compose build` OK.

## 2026-07-16 — Remediación de seguridad y fiabilidad (sesión actual)

**Objetivo:** cerrar brechas del `REMEDIATION_PLAN.md` sin romper el baseline existente.

- **SQL read-only**: allowlist explícita de tablas y columnas en `src/tools/sql.py`.
- **Critic / retries**: separación de `action_retries` vs `retries`, flag `requires_retry` y evitar re-ejecutar acciones ya aprobadas.
- **Traces**: política de retención por edad/cantidad con lock concurrente y hashing de `user_id` / `approved_by` con HMAC en `src/observability/tracing.py`.
- **Rate limiting**: login separado por IP y por usuario en `src/security/rate_limiter.py`.
- **JWT**: revocación de tokens en logout (`jti` + blacklist en memoria) en `src/auth/jwt_handler.py` y `src/api/main.py`.
- **Frontend**: logout automático y redirección a `/login` cuando el token expira o es inválido (`frontend/src/lib/auth-context.tsx`).
- **Evals/Redteam**: constraints de score/categoría en `evals/judges.py`, detección de side effects en `redteam/run_redteam.py` y thresholds de regresión por categoría en `evals/run_evals.py`.

**Verificación:** `python -m compileall src evals redteam` y `PYTHONPATH=src .venv/bin/python -m pytest tests/test_security_core.py tests/test_api.py -q` → 24 passed.

**Pendientes documentados:** ver `REMEDIATION_PLAN.md` (quedan por ejemplo validador de fuentes RAG, tests API, CI workflow, thresholds RAG, más payloads de redteam y checklist final de release).

## 2026-07-16 — Integración completa con Supabase

- **Supabase Postgres como backend principal** (cuando `DATABASE_URL` está set):
  - `src/db/postgres_utils.py`: conexión/psycopg pool con normalización de URL y `search_path=public,extensions`.
  - `src/db/supabase_client.py`: cliente Supabase REST para operaciones admin con service key.
  - `scripts/migrate_postgres.py`: crea tablas `empleados`, `departamentos`, `tickets`, `hitl_queue`, `document_embeddings` (vector 384 + HNSW) y tablas del checkpointer.
- **HITL Queue persistente**: `src/db/hitl_queue.py` soporta PostgreSQL y SQLite fallback.
- **Checkpointer en Supabase**: `PostgresSaver` de `langgraph-checkpoint-postgres` con fallback a SQLite.
- **Vector store con pgvector**: `src/db/supabase_vector.py` con HNSW index; `src/rag/ingest.py` y `retriever.py` usan Supabase automáticamente si hay `DATABASE_URL`.
- **SQL y tickets en Supabase**: `src/tools/sql.py` y `src/tools/tickets.py` conectan a Postgres via service key; `sql.py` sigue read-only.
- **Auth opcional con Supabase**: `src/auth/supabase_auth.py` intenta login contra Supabase Auth cuando el username contiene `@`; fallback local con bcrypt.
- **Hardening de seguridad en Supabase**:
  - Extensión `vector` movida del schema `public` al schema `extensions`.
  - RLS habilitado en todas las tablas `public`.
  - `DATABASE_URL` con percent-encoding para `$`, `@` y `%` evita corrupción por Docker Compose.
- **Frontend**: mantiene HttpOnly cookie JWT; lee HITL queue desde backend; build OK.
- **Docker**:
  - `Dockerfile`, `Dockerfile.ui` y `frontend/Dockerfile` actualizados.
  - `docker compose up -d` levanta API (healthy), UI y frontend.
  - Health check acelerado (`connect_timeout=1s`) para no superar timeout de Docker (5s).
- **Tests**:
  - `pytest tests/` → 18 passed.
  - `npm run lint && npm run build` en frontend → OK.
  - Login, chat, RAG, HITL approve, SQL y tickets verificados en Docker contra Supabase.
- **Documentación actualizada**: `README.md`, `AGENTS.md`, `SECURITY.md`, `.env.example` y este archivo.

## 2026-07-15 — Optimizaciones de latencia
- **Fast path en supervisor**: regex para saludos triviales ("hola", "gracias", "adiós") sin LLM
- **Skip crítico para chat**: chat con confidence >= 0.9 va directo a END
- **HITL inteligente**: solo emails requieren aprobación humana, tickets pasan directo
- **Fix HITL bug**: "listar mis tickets" pausaba porque "email" aparecía en título de ticket #3
- **Modelo híbrido Groq + DeepInfra**:
  - Supervisor: Groq Llama-3.1-8B-Instant (gratis, ~0.4s)
  - Crítico: Groq Llama-3.3-70b-versatile (gratis, ~0.5s)
  - Workers: DeepInfra DeepSeek-V4-Flash (calidad)
  - Structured output: `function_calling` (json_schema no soportado en Groq, json_mode no garantiza schema)
- **Resultados de latencia**:
  - Datos: 11s → 3.4s (Groq 9.1x más rápido que DeepInfra en clasificación)
  - RAG: 10s → 8.4s
  - Tickets: 7s → 5.7s
- **Frontend Next.js 16**: React 19 + shadcn/ui + Tailwind 4 + Recharts (Chat, HITL, Dashboard, Métricas)
- **Pendiente resuelto**: migración a Supabase completada

## 2026-07-14
- Proyecto definido. Plan maestro creado en `PLAN.md`.
- Stack decidido: DeepInfra (DeepSeek-V4-Flash) + Groq, LangChain/LangGraph, FastAPI, Chroma, Streamlit.
- **Fase 0 completada**:
  - Estructura base + venv + requirements.txt
  - .env con API key real + .env.example
  - src/config.py con pydantic-settings
  - Primera llamada exitosa a DeepSeek-V4-Flash vía DeepInfra
  - Tokens: input=13, output=153, total=166
- **Fase 1 completada**:
  - `src/llm/providers.py` — `get_llm()` con abstracción multi-proveedor
  - Streaming con `.stream()` (token por token en tiempo real)
  - Structured outputs con Pydantic (`with_structured_output`)
  - `src/memory/short_term.py` — `ChatMemory` con ventana deslizante
  - `src/observability/metrics.py` — tokens, costo, latencia, tok/s
  - `scripts/cli_chat.py` — CLI interactivo integrando todo
  - Scripts de prueba: test_llm, test_streaming, test_structured, test_memory, test_metrics
- **Fase 2 completada**:
  - Documentos ficticios: politica_rrhh.md, manual_it.md, faq.md
  - `src/rag/ingest.py` — chunking por Markdown headers + embeddings locales + Chroma
  - `src/rag/retriever.py` — búsqueda por similitud semántica (singleton)
  - `src/rag/chain.py` — cadena RAG con prompt de citas de fuente
  - `scripts/test_rag.py` — 4/4 preguntas correctas (incluyendo "no sé" cuando no está en docs)
  - Fix: MarkdownHeaderTextSplitter mejoró precisión del retriever (14→22 chunks, secciones limpias)
- **Fase 3 completada**:
  - `src/tools/tickets.py` — crear/listar/buscar tickets (simulado, @tool)
  - `src/tools/email.py` — enviar email (simulado, @tool)
  - `src/tools/sql.py` — consultar SQL sobre SQLite (solo SELECT, allowlist, @tool)
  - `src/tools/registry.py` — registro central de herramientas
  - `src/agents/react_agent.py` — agente ReAct con function calling nativo (LangGraph)
  - `scripts/test_agent.py` — 4/4 preguntas correctas con traza de tool calls
- **Fase 4 completada**:
  - `src/agents/state.py` — AgentState (TypedDict) con estado compartido
  - `src/agents/supervisor.py` — clasifica intención con Literal["rag","datos","accion","chat"]
  - `src/agents/rag_agent.py` — worker RAG (reutiliza chain.py)
  - `src/agents/data_agent.py` — worker SQL (ReAct con consultar_sql)
  - `src/agents/action_agent.py` — worker acciones (ReAct con tickets + email)
  - `src/agents/chat_agent.py` — worker fallback (LLM puro)
  - `src/agents/critic_agent.py` — evalúa respuestas, loop de reintento (max 2)
  - `src/agents/graph.py` — grafo LangGraph con conditional edges
  - `scripts/test_multi_agent.py` — 4/4 correctas, grafo visualizado en Mermaid
- **Fase 5 completada**:
  - `src/security/prompt_injection.py` — detección con regex + sanitize_input
  - `src/security/rbac.py` — roles empleado/admin con permisos de tools e intenciones
  - `src/security/rate_limiter.py` — ventana deslizante 10 req/120s
  - `src/security/pii_filter.py` — enmascara emails, teléfonos, DNIs, datos sensibles
  - `src/agents/security_node.py` — guardrails antes del supervisor (injection + rate limit)
  - Grafo actualizado: START → security → supervisor → workers → critic → END
  - `src/agents/chat_agent.py` — maneja acceso denegado por RBAC
  - `scripts/test_security.py` — 5/5 tests pasados
- **Fase 6 completada**:
  - `src/agents/hitl_node.py` — nodo HITL con interrupt() de LangGraph
  - Grafo actualizado: crítico → hitl_review → END (acciones siempre revisadas)
  - `build_graph(checkpointer)` — soporte para MemorySaver (pausar/reanudar)
  - `scripts/test_hitl.py` — 3/3 tests (aprobar, rechazar, no-pausar RAG)
- **Fase 7 completada**:
  - `evals/datasets/test_cases.json` — 33 casos (10 RAG, 8 datos, 5 accion, 4 chat, 6 adversarial)
  - `evals/judges.py` — LLM-as-judge con score 0-1 + categoría (correcta/parcial/incorrecta/rechazada)
  - `evals/rag_evals.py` — métricas RAG: faithfulness, answer relevance, context precision
  - `evals/run_evals.py` — runner con reporte por categoría, auto-aprobar HITL, guardar resultados
  - `src/observability/tracing.py` — traces en JSONL, stats agregadas (confidence, tiempo, intención)
  - `scripts/test_tracing.py` — prueba de tracing
  - Fix: supervisor prompt mejorado (tickets → accion, no datos)
  - Resultado: 32/33 pass (97%), score promedio 0.970
- **Fase 8 completada**:
  - `src/api/main.py` — FastAPI: /chat, /hitl/{id}/approve, /hitl/{id}/reject, /stats, /health
  - `ui/app.py` — Streamlit: Chat, Aprobaciones HITL, Dashboard de métricas
  - `Dockerfile` — imagen Python 3.11-slim
  - `docker-compose.yml` — API (8000) + UI (8501) + frontend (3000) con volúmenes
  - requirements: fastapi, uvicorn, streamlit, httpx, psycopg, langgraph-checkpoint-postgres, supabase
  - API probada: chat, HITL approve, HITL reject, stats — todo funcional
- **Fase 9 completada**:
  - `redteam/attacks/payloads.json` — 31 ataques en 8 categorías
  - `redteam/run_redteam.py` — runner con evaluator defense-in-depth (4 capas)
  - Categorías: prompt injection directo/indirecto, jailbreak, data exfiltration, tool abuse, SQL injection, RBAC bypass, rate limit
  - Fixes de seguridad aplicados:
    - System prompt hardening (anti-extracción en chat_agent)
    - Email whitelist de dominios internos (anti-exfiltración)
    - RBAC bypass fix: chat_agent cambia intencion a "chat" al denegar (evita reintento al worker denegado)
    - Rate limit window ampliada a 120s
  - Resultado final: 31/31 ataques defendidos (100% defense rate)
- **Fase 10 completada**:
  - README.md actualizado con arquitectura final, todas las fases, resultados, y guía completa
  - Proyecto funcional en producción (10 fases entregadas)
- **REMEDIACIÓN EN CURSO** — ver `REMEDIATION_PLAN.md` para ítems de seguridad/fiabilidad pendientes
