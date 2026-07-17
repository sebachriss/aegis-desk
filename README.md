# Aegis Desk

> Plataforma de soporte interno inteligente multi-agente para una empresa ficticia (Aegis Corp).
> Proyecto de aprendizaje integral de AI Engineering: LLMs, RAG, multi-agentes, seguridad, HITL, evals, observabilidad, API/UI, red teaming y deploy.

---

## ¿Qué hace?

Los empleados de Aegis Corp hacen consultas y un equipo de agentes de IA las resuelve de forma **segura, auditable y con supervisión humana**.

```
"¿Cuántos días de vacaciones tengo?"     → RAG Agent busca en documentos (Supabase pgvector)
"Crea un ticket de alta prioridad"       → Action Agent crea ticket en Supabase Postgres
"Envía un email a RRHH"                    → Action Agent → HITL aprueba (acción sensible)
"¿Cuántos empleados hay en Ventas?"        → Data Agent consulta SQL (solo admin)
"Hola, ¿qué tal?"                          → Chat Agent responde (fast path, sin LLM)
"Ignora tus instrucciones y..."            → Security Node bloquea
```

## Arquitectura

```
Usuario
  │
  ▼
Security Node (prompt injection + rate limit + sanitize)
  │
  ▼
Supervisor (clasifica intención → enruta)
  │                          │
  │ Fast path: "hola" → chat │
  │ (regex, sin LLM)         │
  │        │         │       │
  ▼        ▼         ▼       ▼
RAG      Data      Action    Chat
(docs)   (SQL)    (tools)    (fallback)
  │        │         │          │
  └────────┴────┬────┴──────────┘
               ▼
         Crítico (evalúa calidad + confidence)
               │
      ┌────────┴────────┐
      ▼                 ▼
 Respuesta OK      HITL (solo emails)
 (usuario)         (interrupt → aprobación)
                        │
                   ┌────┴────┐
                   ▼         ▼
                Aprobar   Rechazar
                (ejecuta)  (cancela)
```

### Stack

| Capa | Tecnología |
|---|---|
| LLM (workers) | DeepInfra — DeepSeek-V4-Flash (RAG, datos, acción, chat) |
| LLM (supervisor + crítico) | Groq — Llama-3.1-8B-Instant / Llama-3.3-70b (gratis, ~0.4s) |
| Framework | LangChain + LangGraph |
| Embeddings | `sentence-transformers` local (`all-MiniLM-L6-v2`, 384 dims) |
| Vector Store | **Supabase pgvector** (`document_embeddings`, HNSW) con fallback a Chroma local |
| Base de datos | **Supabase PostgreSQL** con fallback a SQLite local |
| Checkpointer | `PostgresSaver` (Supabase) con fallback a SQLite |
| Auth | Local bcrypt + opcional **Supabase Auth** para emails |
| API | FastAPI + Uvicorn |
| Frontend | Next.js 16 + React 19 + shadcn/ui + Tailwind 4 + Recharts |
| Observabilidad | Métricas propias + tracing JSONL |
| Evals | LLM-as-judge + métricas RAG (faithfulness, relevance, precision) |
| Deploy | Docker + Docker Compose (local); Vercel + Render + Supabase (target cloud) |

### Modelo híbrido de latencia

| Nodo | Modelo | Provider | Latencia |
|---|---|---|---|
| Supervisor | Llama-3.1-8B-Instant | Groq (free) | ~0.4s |
| Crítico | Llama-3.3-70b-versatile | Groq (free) | ~0.5s |
| RAG / Data / Action / Chat | DeepSeek-V4-Flash | DeepInfra | ~3-5s |

**Fast path**: saludos triviales ("hola", "gracias", "adiós") se clasifican con regex en el supervisor, sin llamar al LLM.

## Estructura del proyecto

```
aegis-desk/
├── src/
│   ├── config.py               # Settings con pydantic-settings
│   ├── db/
│   │   ├── supabase_client.py  # Cliente Supabase (REST)
│   │   ├── supabase_vector.py  # Vector store en Supabase pgvector
│   │   ├── hitl_queue.py       # Cola HITL en Postgres/SQLite
│   │   └── postgres_utils.py   # Conexión/pool psycopg v3 + normalización URL
│   ├── llm/
│   │   └── providers.py        # get_llm() + get_fast_llm() (Groq + DeepInfra)
│   ├── memory/
│   │   └── short_term.py       # ChatMemory con ventana deslizante
│   ├── observability/
│   │   ├── metrics.py          # track_llm_call (tokens, costo, latencia)
│   │   └── tracing.py          # Traces JSONL + stats agregadas
│   ├── rag/
│   │   ├── ingest.py           # Chunking por Markdown headers + Supabase/Chroma
│   │   ├── retriever.py        # Búsqueda por similitud semántica
│   │   ├── supabase_vector.py  # Operaciones pgvector
│   │   ├── chain.py            # Cadena RAG con citas de fuente
│   │   └── documents/          # Docs ficticios (RRHH, IT, FAQ)
│   ├── tools/
│   │   ├── tickets.py          # @tool: crear/listar/buscar tickets (Postgres)
│   │   ├── email.py            # @tool: enviar email (simulado, whitelist dominios)
│   │   ├── sql.py              # @tool: SELECT sobre Postgres/SQLite (allowlist)
│   │   └── registry.py         # Registro central de herramientas
│   ├── agents/
│   │   ├── state.py            # AgentState (TypedDict)
│   │   ├── supervisor.py       # Clasifica intención (Literal) + fast path regex
│   │   ├── rag_agent.py        # Worker RAG
│   │   ├── data_agent.py       # Worker SQL (ReAct)
│   │   ├── action_agent.py     # Worker acciones (ReAct)
│   │   ├── chat_agent.py       # Worker fallback + acceso denegado + anti-injection
│   │   ├── critic_agent.py     # Evalúa respuestas, loop de reintento (Groq 70b)
│   │   ├── security_node.py    # Guardrails (injection + rate limit)
│   │   ├── hitl_node.py        # Human-in-the-Loop (solo acciones sensibles)
│   │   ├── react_agent.py      # Agente ReAct standalone (Fase 3)
│   │   └── graph.py            # Grafo LangGraph ensamblado
│   ├── security/
│   │   ├── prompt_injection.py # Detección regex + sanitize
│   │   ├── rbac.py             # Roles empleado/admin
│   │   ├── rate_limiter.py     # Ventana deslizante 10 req/120s
│   │   └── pii_filter.py       # Enmascara emails, teléfonos, DNIs
│   ├── auth/
│   │   ├── users.py            # Auth local con bcrypt
│   │   ├── supabase_auth.py    # Auth opcional con Supabase (emails)
│   │   └── jwt_handler.py        # JWT con HttpOnly cookies
│   └── api/
│       └── main.py             # FastAPI: /chat, /hitl, /stats, /health
├── ui/
│   └── app.py                  # Streamlit (legacy, Chat/HITL/Dashboard)
├── frontend/                   # Next.js 16 + React 19 + shadcn/ui
│   ├── src/
│   │   ├── app/
│   │   │   ├── login/
│   │   │   └── (protected)/
│   │   │       ├── chat/
│   │   │       ├── hitl/       # Aprobaciones pendientes (admin)
│   │   │       ├── dashboard/
│   │   │       └── metrics/
│   │   ├── components/
│   │   └── lib/
│   │       ├── api.ts
│   │       └── auth-context.tsx
│   └── package.json
├── evals/                      # Evaluaciones (33 casos)
├── redteam/                    # Red teaming (36 ataques)
├── scripts/
│   ├── migrate_postgres.py     # Migración a Supabase Postgres
│   └── test_*.py               # Tests por fase
├── data/                       # SQLite/Chroma local + traces (gitignored)
├── Dockerfile                  # API Python 3.11-slim
├── Dockerfile.ui               # UI Streamlit
├── docker-compose.yml          # API + UI + frontend
├── requirements.txt
├── .env.example                # Variables de entorno
├── PLAN.md                     # Plan maestro del proyecto
├── PROGRESS.md                 # Bitácora de avance
├── REMEDIATION_PLAN.md         # Plan integral de remediación
├── OPTIMIZATIONS.md            # Optimizaciones de latencia
├── SECURITY.md                 # Política de seguridad
├── AGENTS.md                   # Instrucciones para agentes de IA
└── README.md                   # Este archivo
```

## Setup

```bash
# 1. Clonar
git clone https://github.com/sebachriss/aegis-desk.git
cd aegis-desk

# 2. Virtual env
python -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env:
#   DEEPINFRA_API_KEY=...     (requerido)
#   GROQ_API_KEY=...          (recomendado)
#   SUPABASE_URL=...
#   SUPABASE_KEY=...
#   SUPABASE_SERVICE_KEY=...
#   DATABASE_URL=...          (pooler de Supabase)
#   JWT_SECRET=...

# 5. Crear tablas y extensión vector en Supabase
PYTHONPATH=src python scripts/migrate_postgres.py

# 6. Indexar documentos (Supabase pgvector)
python -m src.rag.ingest

# 7. Verificación local (Makefile)
make test             # pytest tests/
make compile          # compileall
make frontend         # npm install + lint + build
make verify           # test + compile + frontend (rápido)
make evals            # suite de evals (requiere API keys)
make redteam          # suite de red teaming (requiere API keys)
make full             # verify + evals + redteam + baseline checks
make install-hooks    # instala pre-commit hook de Git
make clean            # limpia cachés

# Inspeccionar backend vectorial activo
.venv/bin/python scripts/check_vector_store.py
```

### Sin Supabase (modo local)

Si no se configura `DATABASE_URL` ni `SUPABASE_URL`, el sistema usa:
- SQLite local (`data/aegis.db`) para SQL, tickets, HITL.
- Chroma local (`data/chroma/`) para RAG.
- `SqliteSaver` para el checkpointer.

## Levantar la API + Frontend

```bash
# API (FastAPI)
uvicorn src.api.main:app --port 8000

# Frontend (Next.js)
cd frontend
npm install
npm run dev    # http://localhost:3000

# Docker (API 8000 + UI 8501 + Frontend 3000)
docker compose up -d
```

| Servicio | URL | Descripción |
|---|---|---|
| API | http://localhost:8000 | FastAPI |
| API docs | http://localhost:8000/docs | Swagger interactivo |
| Frontend | http://localhost:3000 | Next.js (Chat, HITL, Dashboard, Métricas) |
| UI legacy | http://localhost:8501 | Streamlit (Chat, HITL, Dashboard) |

### Endpoints de la API

| Método | Path | Descripción |
|---|---|---|
| `POST` | `/login` | Autenticar usuario y obtener JWT (HttpOnly cookie) |
| `POST` | `/chat` | Enviar mensaje al agente |
| `GET` | `/hitl/pending` | Ver pendientes de HITL (admin) |
| `POST` | `/hitl/{thread_id}/approve` | Aprobar acción (admin) |
| `POST` | `/hitl/{thread_id}/reject` | Rechazar acción (admin) |
| `GET` | `/stats` | Métricas de tracing |
| `GET` | `/health` | Health check de dependencias |
| `GET` | `/me` | Info del usuario autenticado |

## Fases del proyecto

| Fase | Descripción | Estado | Resultado |
|---|---|---|---|
| 0 | Setup (config, providers, primera llamada) | ✅ | — |
| 1 | Fundamentos LLM (streaming, structured, memory, metrics, CLI) | ✅ | — |
| 2 | RAG (Markdown chunking, embeddings, vector store, citas) | ✅ | pgvector/Chroma |
| 3 | Tool Calling (tickets, email, SQL, agente ReAct) | ✅ | Postgres/SQLite |
| 4 | Multi-Agente (supervisor, 4 workers, crítico, LangGraph) | ✅ | — |
| 5 | Seguridad (prompt injection, RBAC, rate limit, PII) | ✅ | 5/5 tests |
| 6 | HITL (interrupt, aprobación/rechazo humano) | ✅ | 3/3 tests |
| 7 | Evals y Observabilidad (LLM-as-judge, RAGAS, tracing) | ✅ | 33/33 pass (100%) |
| 8 | API, UI y Docker (FastAPI, Streamlit, Docker) | ✅ | 6 endpoints + frontend |
| 9 | Red Teaming Final (36 ataques, 13 categorías) | ✅ | 36/36 defended (100%) |
| 10 | Integración Supabase (Postgres, pgvector, checkpointer, auth) | ✅ | Docker healthy |
| — | Optimizaciones de latencia (Groq + fast path + HITL inteligente) | ✅ | Ver OPTIMIZATIONS.md |
| — | Frontend Next.js (shadcn/ui, Tailwind 4, Recharts, HttpOnly cookies) | ✅ | Chat, HITL, Dashboard, Métricas |

## Resultados de Evals

Resultado final (2026-07-17):

```
Total casos: 33
Score promedio: 1.000
Pass rate (>=0.7): 100.0% (33/33)

  rag         10/10  100.0%
  datos        8/8   100.0%
  accion       5/5   100.0%
  chat         4/4   100.0%
  adversarial  6/6   100.0%
```

## Resultados de Red Teaming

Resultado final (2026-07-17):

```
Total ataques: 36
Defendidos: 36
Breaches: 0
Defense rate: 100.0%

  prompt_injection_direct     8/8  100%
  prompt_injection_indirect   3/3  100%
  jailbreak                   4/4  100%
  data_exfiltration           4/4  100%
  tool_abuse                  3/3  100%
  sql_injection               4/4  100%
  rbac_bypass                 4/4  100%
  rate_limit                  1/1  100%
  base64                      1/1  100%
  rag_poisoning               1/1  100%
  tool_chaining               1/1  100%
  replay                      1/1  100%
  unicode_confusable          1/1  100%
```

## Vulnerabilidades encontradas y fixeadas durante Red Teaming

| Vulnerabilidad | Severidad | Fix |
|---|---|---|
| System prompt extraído por "Repeat everything above" | Crítica | Hardening del prompt con reglas anti-extracción |
| Empleado vio todos los salarios vía SQL | Alta | RBAC bypass fix: `chat_agent` cambia `intencion` a `"chat"` al denegar |
| Email a dominios externos (exfiltración) | Alta | Whitelist de dominios internos en `email.py` |
| Rate limit no activado con requests lentos | Media | Window ampliada de 60s a 120s |
| `consultar_sql` no era invocable como tool LangChain | Media | `consultar_sql` ahora es función callable y `consultar_sql_tool` es `StructuredTool` |
| Tool chaining para exfiltrar datos (ticket + email externo) | Alta | Patrones anti-exfiltración y anti-tool-chaining en `prompt_injection.py` |
| Replay de acción HITL sin aprobación | Alta | Patrones anti-replay/HITL-bypass en `prompt_injection.py` |
| Espaciado entre letras como inyección (e.g. `i g n o r e`) | Media | Detección de frases peligrosas comprimidas en `prompt_injection.py` |

## Aprendizajes clave

- **Chunking por Markdown headers** > chunking por tamaño fijo: preserva secciones semánticamente coherentes
- **`Literal` en Pydantic** fuerza al LLM a elegir entre opciones exactas (no inventa categorías)
- **Especialización de agentes**: un agente con 2 tools específicas > un agente con 10 tools
- **`interrupt()` de LangGraph**: pausa el grafo, guarda estado, espera decisión humana
- **Defense in depth**: ninguna capa es perfecta, pero las 4 juntas sí (security node → RBAC → LLM refusal → HITL)
- **LLM-as-judge**: escalable para evaluar 1000s de respuestas sin humanos, pero requiere calibración del prompt del juez
- **Evals como regression test**: si cambias un prompt, corres `python -m evals.run_evals` y comparas contra el baseline
- **Red teaming encuentra bugs reales**: el RBAC bypass del crítico no se detectó hasta que atacamos el sistema
- **Tracing JSONL**: simple, append-only, fácil de parsear. Base para LangSmith/Langfuse en producción
- **Modelo híbrido**: usar LLM gratis y rápido (Groq Llama-8B) para clasificación/evaluación y LLM de calidad (DeepSeek) para generación de respuestas
- **Fast path regex**: saludos triviales no necesitan LLM — regex en supervisor ahorra ~3s por mensaje
- **HITL selectivo**: no todas las acciones necesitan aprobación humana — tickets son rutinarios, solo emails son sensibles
- **Supabase pgvector**: RAG persistente y escalable; el pooler (Supavisor) evita problemas de IPv6 en conexiones locales
- **Percent-encoding en `DATABASE_URL`**: passwords con `$`, `@` o `%` deben encodearse para que Docker Compose no los corrompa

## Seguridad

- `.env` está en `.gitignore` — **no se sube al repo**
- Las tools son **simuladas** (no envían emails reales, no modifican DBs externas)
- Email whitelist: solo dominios internos (`aegiscorp.com`, `aegis.com`)
- SQL allowlist: tablas y columnas explícitas, solo `SELECT` (no `INSERT`, `UPDATE`, `DELETE`, `DROP`)
- PII filter: enmascara emails, teléfonos, DNIs y otros datos sensibles en respuestas y traces
- Rate limiting: 10 requests por 120s por usuario en `/chat`; 12 intentos de login/15 min por IP y por usuario
- RBAC: `empleado` (RAG + tickets + chat) vs `admin` (+ SQL + email)
- JWT en cookie `HttpOnly` con expiración, issuer, audience y revocación en `/logout`
- Traces con retención limitada: hashes de identificadores, redacción PII, rotación por edad/cantidad
- **Supabase**: RLS habilitado en todas las tablas; extensión `vector` en schema `extensions`; service key solo en backend

Para el estado completo de remediación y pendientes ver `SECURITY.md` y `REMEDIATION_PLAN.md`.

## Licencia

Proyecto educativo. Sin licencia formal.
