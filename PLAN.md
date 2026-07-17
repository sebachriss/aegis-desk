# Aegis Desk — Plan Maestro del Proyecto

## Estado actual (2026-07-16)

El plan maestro se completó y se integró Supabase como backend principal:

- Backend: FastAPI + LangGraph con checkpointer `PostgresSaver` (Supabase), HITL queue en Postgres, SQL/tickets en Supabase, RAG en Supabase pgvector.
- Auth: local bcrypt + Supabase Auth opcional para emails; JWT en cookie `HttpOnly`.
- Frontend: Next.js 16 con cookies HttpOnly; consume `/chat`, `/hitl/pending`, `/hitl/{id}/approve|reject`, `/stats`, `/health`.
- Docker: `docker compose up -d` levanta API, UI legacy y frontend; healthchecks pasan.
- Seguridad: RLS en todas las tablas `public`; `vector` en schema `extensions`; passwords con bcrypt; SQL read-only allowlist; email whitelist; PII filter.
- Tests: `pytest` 18/18, frontend lint+build OK, Red Teaming 31/31 defendido.

Las secciones siguientes describen el plan original; los detalles de implementación final se encuentran en `README.md`, `AGENTS.md` y `PROGRESS.md`.

> Plataforma de Soporte Interno Inteligente Multi-Agente.
> Proyecto de aprendizaje integral de AI Engineering: LLMs, RAG, multi-agentes,
> LangChain/LangGraph, seguridad, human-in-the-loop, evals y observabilidad.

---

## 1. Visión General

Sistema de asistencia empresarial interna (empresa ficticia) donde empleados hacen
consultas y un equipo de agentes de IA las resuelve de forma **segura, auditable y
con supervisión humana**.

### Objetivos de aprendizaje
- Dominar el ciclo completo de AI Engineering, no solo "llamar a un LLM".
- Construir cada componente entendiendo el porqué (control total del código).
- Terminar con un proyecto de portafolio serio y desplegable.

---

## 2. Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| LLM Provider principal | DeepInfra — `deepseek-ai/DeepSeek-V4-Flash` ($0.09/$0.18 por M tokens, 1M ctx, function calling, JSON mode) |
| LLM Provider secundario | Groq (tier gratis, velocidad extrema) — Llama-3.1-8B-Instant (supervisor) + Llama-3.3-70b (crítico) |
| Razonamiento profundo (puntual) | DeepSeek-R1 / V4 full en DeepInfra |
| Framework LLM | LangChain (core, abstracciones) |
| Orquestación de agentes | LangGraph (grafos, estado, interrupts) |
| Embeddings | `sentence-transformers` local (gratis) |
| Vector Store | Chroma (local) → migrable a Pinecone (cloud) |
| Backend | FastAPI (streaming SSE, async) |
| Frontend | Next.js 16 + React 19 + shadcn/ui + Tailwind 4 + Recharts |
| Base de datos | SQLite → Supabase PostgreSQL (migración cloud) |
| Observabilidad | Métricas propias + tracing JSONL |
| Evals | Dataset propio + LLM-as-judge + RAGAS |
| Seguridad | Guardrails propios (regex + LLM refusal) |
| Infra | Docker, docker-compose, `.env`, Vercel (frontend), Render (API) |

### Presupuesto
- $10 en DeepInfra ≈ 80M+ tokens con V4-Flash ≈ ~2,500 sesiones de agente. Sobra.
- Groq gratis para desarrollo diario e iteración.
- Regla: modelos chicos/baratos para tareas simples (router, guardrails), modelo
  grande solo donde importa (razonamiento, crítico).

---

## 3. Arquitectura Objetivo

```
Usuario (UI Streamlit / API)
        │
        ▼
┌─────────────────────────────────────┐
│  CAPA DE SEGURIDAD (entrada)        │  ← prompt injection, PII, moderación
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  SUPERVISOR (LangGraph)             │  ← clasifica intención, enruta, decide
└─────────────────────────────────────┘
   │        │         │          │
   ▼        ▼         ▼          ▼
 RAG     Datos     Acciones   Chat general
 Agent   Agent     Agent      (fallback)
 (docs)  (SQL)     (tools)
   │        │         │          │
   └────────┴────┬────┴──────────┘
                 ▼
┌─────────────────────────────────────┐
│  AGENTE CRÍTICO (reflection)        │  ← revisa calidad/seguridad de respuesta
└─────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
   Respuesta OK      HUMAN-IN-THE-LOOP
   (usuario)         (interrupt → aprobación)
                 │
                 ▼
┌─────────────────────────────────────┐
│  CAPA DE SEGURIDAD (salida)         │  ← PII redaction, jailbreak check
└─────────────────────────────────────┘

Transversal: Observabilidad (tracing, tokens, costos, latencia) + Memoria
```

---

## 4. Estructura de Carpetas (objetivo final)

```
aegis-desk/
├── PLAN.md                     # este archivo
├── PROGRESS.md                 # bitácora de avance por fase
├── README.md
├── requirements.txt
├── .env.example
├── docker-compose.yml
├── src/
│   ├── config.py               # settings, providers, modelos
│   ├── llm/
│   │   ├── providers.py        # abstracción multi-proveedor + fallback
│   │   └── router.py           # routing por costo/complejidad
│   ├── memory/
│   │   ├── short_term.py       # historial conversacional
│   │   └── long_term.py        # memoria persistente por usuario
│   ├── rag/
│   │   ├── ingest.py           # chunking, embeddings, indexación
│   │   ├── retriever.py        # búsqueda híbrida, re-ranking
│   │   └── documents/          # docs ficticios de la empresa
│   ├── agents/
│   │   ├── state.py            # estado compartido del grafo
│   │   ├── supervisor.py       # router de intenciones
│   │   ├── rag_agent.py
│   │   ├── data_agent.py       # text-to-SQL validado
│   │   ├── action_agent.py     # tool calling (tickets, emails)
│   │   ├── critic_agent.py     # reflection / auto-evaluación
│   │   └── graph.py            # ensamblaje LangGraph
│   ├── tools/
│   │   ├── registry.py         # registro con permisos por rol
│   │   ├── tickets.py
│   │   ├── email.py            # simulado
│   │   └── sql.py              # allowlist, solo SELECT
│   ├── security/
│   │   ├── input_guard.py      # anti prompt-injection (heurísticas + LLM)
│   │   ├── output_guard.py     # PII redaction, moderación
│   │   ├── permissions.py      # RBAC de herramientas
│   │   └── rate_limit.py
│   ├── hitl/
│   │   ├── interrupts.py       # pausas de LangGraph para aprobación
│   │   └── review_queue.py     # cola de revisión humana
│   ├── observability/
│   │   ├── tracing.py          # Langfuse/LangSmith
│   │   └── metrics.py          # tokens, costo, latencia, tok/s
│   └── api/
│       ├── main.py             # FastAPI app
│       └── routes/
├── ui/
│   └── app.py                  # Streamlit
├── evals/
│   ├── datasets/               # casos de prueba (JSON/YAML)
│   ├── judges.py               # LLM-as-judge
│   ├── rag_evals.py            # faithfulness, relevance (RAGAS)
│   └── run_evals.py
├── redteam/
│   ├── attacks/                # payloads de prompt injection, jailbreaks
│   └── run_redteam.py
└── tests/
    ├── test_llm.py
    ├── test_agents.py
    ├── test_security.py
    └── ...
```

---

## 5. Fases del Proyecto

> Cada fase produce algo **funcional y demostrable**. No se avanza a la siguiente
> sin tests básicos y una entrada en `PROGRESS.md`.

### ✅ Fase 0 — Setup (½ día)
- [x] Crear estructura base del proyecto, venv, `requirements.txt`.
- [x] `.env` con `DEEPINFRA_API_KEY` y `GROQ_API_KEY` (+ `.env.example` sin secretos).
- [x] `config.py` con settings (pydantic-settings).
- [x] Primera llamada exitosa a DeepSeek-V4-Flash vía DeepInfra.

### ✅ Fase 1 — Fundamentos LLM (2-3 días)
- [x] Abstracción multi-proveedor (`providers.py`): DeepInfra + Groq con interfaz común.
- [x] Chat con streaming (async generators).
- [x] Structured outputs (Pydantic + function_calling).
- [x] Memoria conversacional short-term (ventana deslizante).
- [x] Medidor de métricas por llamada: tokens, costo, latencia, tok/s.
- [x] CLI de chat funcional para probar todo.

### ✅ Fase 2 — RAG (3-4 días)
- [x] Crear docs ficticios de la empresa (políticas RRHH, manual IT, FAQ).
- [x] Pipeline de ingesta: chunking por Markdown headers + embeddings locales + Chroma.
- [x] Retriever: búsqueda por similitud semántica.
- [x] Cadena RAG con citas de fuentes.

### ✅ Fase 3 — Tool Calling y Primer Agente (2-3 días)
- [x] Registro de herramientas (`registry.py`): tickets, email simulado, consulta SQL.
- [x] Agente ReAct con function calling nativo de V4-Flash.
- [x] Agente de Datos: text-to-SQL sobre SQLite con validación (solo SELECT, allowlist).
- [x] Manejo de errores de tools (retry, mensajes al LLM).

### ✅ Fase 4 — Sistema Multi-Agente con LangGraph (4-5 días)
- [x] Definir estado compartido (`state.py`) con TypedDict.
- [x] Supervisor: clasificación de intención (Groq Llama-3.1-8B) y enrutamiento.
- [x] Integrar RAG Agent, Data Agent, Action Agent como nodos.
- [x] Agente Crítico (reflection): Groq Llama-3.3-70b evalúa respuesta, loop con límite.
- [x] Checkpointing de LangGraph (MemorySaver, threads por conversación).
- [x] Visualizar el grafo (mermaid).

### ✅ Fase 5 — Seguridad (3-4 días)
- [x] Input guard: heurísticas regex + sanitize de prompt injection.
- [x] Output guard: PII redaction (emails, teléfonos, DNIs).
- [x] RBAC: permisos de herramientas por rol (empleado/admin).
- [x] Sandboxing SQL: allowlist estricta, solo SELECT.
- [x] Rate limiting por usuario (10 req/120s).

### ✅ Fase 6 — Human-in-the-Loop (2-3 días)
- [x] `interrupt` de LangGraph antes de acciones sensibles (solo emails).
- [x] Cola de revisión: respuestas con baja confianza van a aprobación.
- [x] UI de aprobación (aprobar / rechazar) en Streamlit y Next.js.
- [x] Reanudación del grafo tras decisión humana (checkpointing).

### ✅ Fase 7 — Evals y Observabilidad (3-4 días)
- [x] Tracing JSONL: query, intención, respuesta, confidence, tiempo, fuentes.
- [x] Dashboard de métricas (stats agregadas por intención).
- [x] Dataset de evaluación: 33 casos (RAG, datos, acción, chat, adversarial).
- [x] LLM-as-judge para calidad de respuestas.
- [x] Métricas RAG: faithfulness, answer relevance, context precision.
- [x] Resultado: 32/33 pass (97%), score promedio 0.970.

### ✅ Fase 8 — API, UI y Deploy (3-4 días)
- [x] FastAPI: /login, /chat, /hitl, /stats, /health, /me (8 endpoints).
- [x] Frontend Next.js 16: Chat, HITL, Dashboard, Métricas (shadcn/ui + Tailwind 4).
- [x] Streamlit UI legacy: chat, aprobaciones HITL, dashboard.
- [x] Dockerizar (API + Streamlit) con docker-compose.
- [x] README con arquitectura, decisiones y demo.

### ✅ Fase 9 — Red Teaming Final (2 días)
- [x] Suite de 31 ataques automatizados en 8 categorías.
- [x] Defense-in-depth evaluator (4 capas).
- [x] 4 vulnerabilidades encontradas y fixeadas (system prompt leak, RBAC bypass, email exfiltration, rate limit).
- [x] Resultado: 31/31 ataques defendidos (100% defense rate).

### ✅ Fase 10 — Cierre y Documentación
- [x] README.md completo con arquitectura, stack, resultados, guía de setup.
- [x] PROGRESS.md con bitácora de todas las fases.
- [x] SECURITY.md con política de reporte de vulnerabilidades.
- [x] OPTIMIZATIONS.md con optimizaciones de latencia y pendientes.

### 🔲 Extras (post-proyecto)
- [ ] Migración a Supabase (auth + PostgreSQL) — resolver tickets compartidos
- [ ] Migración a Pinecone (vector DB cloud)
- [ ] Deploy en Render (API) + Vercel (frontend)
- [ ] Evals con modelo híbrido (regression test)
- [ ] Streaming al frontend (percepción de menor latencia)
- [ ] Memoria long-term semántica por usuario
- [ ] MCP (Model Context Protocol) para exponer tools
- [ ] Multi-modalidad (análisis de imágenes en tickets)

---

## 6. Convenciones de Trabajo

- **Bitácora**: cada sesión termina actualizando `PROGRESS.md` (qué se hizo, qué falta, decisiones).
- **Tests primero en lo crítico**: seguridad y tools siempre con tests.
- **Commits por fase/feature** con mensajes descriptivos.
- **Sin secretos en código**: todo por `.env`.
- **Aprender > copiar**: cada componente se implementa entendiéndolo; librerías externas solo tras construir la versión propia (donde aplique, ej: guardrails).

## 7. Estimación Total

~25-30 días de trabajo efectivo (a tu ritmo). Presupuesto: $10 DeepInfra + tiers gratis.

---
*Creado: 2026-07-14. Actualizar este plan cuando cambien decisiones de arquitectura.*
