# Aegis Desk — Plan Maestro del Proyecto

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
| LLM Provider secundario | Groq (tier gratis, velocidad extrema) — Llama 3.3 70B |
| Razonamiento profundo (puntual) | DeepSeek-R1 / V4 full en DeepInfra |
| Framework LLM | LangChain (core, abstracciones) |
| Orquestación de agentes | LangGraph (grafos, estado, interrupts) |
| Embeddings | BGE en DeepInfra o `sentence-transformers` local (gratis) |
| Vector Store | Chroma (local, simple) → migrable a pgvector/Qdrant |
| Backend | FastAPI (streaming SSE, async) |
| Frontend | Streamlit (rápido al inicio) → React opcional en fase final |
| Base de datos | SQLite → PostgreSQL (fase avanzada) |
| Observabilidad | Langfuse (self-hosted, gratis) o LangSmith (tier gratis) |
| Evals | Dataset propio + LLM-as-judge + RAGAS |
| Seguridad | Guardrails propios + LLM Guard / Rebuff (comparación) |
| Infra | Docker, docker-compose, `.env`, pytest, CI (GitHub Actions) |

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
- [ ] Crear estructura base del proyecto, venv, `requirements.txt`.
- [ ] `.env` con `DEEPINFRA_API_KEY` y `GROQ_API_KEY` (+ `.env.example` sin secretos).
- [ ] `config.py` con settings (pydantic-settings).
- [ ] Primera llamada exitosa a DeepSeek-V4-Flash vía DeepInfra.
- **Aprendizajes**: setup profesional, manejo de secretos, APIs OpenAI-compatible.

### 🔲 Fase 1 — Fundamentos LLM (2-3 días)
- [ ] Abstracción multi-proveedor (`providers.py`): DeepInfra + Groq con interfaz común y fallback automático.
- [ ] Chat con streaming (async generators).
- [ ] Structured outputs (Pydantic + JSON mode).
- [ ] Memoria conversacional short-term (ventana + resumen).
- [ ] Medidor de métricas por llamada: tokens, costo, latencia, tok/s (base de observabilidad).
- [ ] CLI de chat funcional para probar todo.
- **Aprendizajes**: streaming, tokens/costos, prompt engineering, context management.

### 🔲 Fase 2 — RAG (3-4 días)
- [ ] Crear docs ficticios de la empresa (políticas RRHH, manual IT, FAQ).
- [ ] Pipeline de ingesta: chunking (probar estrategias), embeddings, Chroma.
- [ ] Retriever: similarity → luego búsqueda híbrida (BM25 + vectorial) y re-ranking.
- [ ] Cadena RAG con citas de fuentes.
- [ ] Comparar: embeddings locales vs BGE en DeepInfra.
- **Aprendizajes**: chunking, embeddings, retrieval, grounding, hallucination mitigation.

### 🔲 Fase 3 — Tool Calling y Primer Agente (2-3 días)
- [ ] Registro de herramientas (`registry.py`): tickets, email simulado, consulta SQL.
- [ ] Agente ReAct con function calling nativo de V4-Flash.
- [ ] Agente de Datos: text-to-SQL sobre SQLite con validación (solo SELECT, allowlist de tablas).
- [ ] Manejo de errores de tools (retry, mensajes al LLM).
- **Aprendizajes**: function calling, ReAct, agentes con herramientas, validación de salidas.

### 🔲 Fase 4 — Sistema Multi-Agente con LangGraph (4-5 días)
- [ ] Definir estado compartido (`state.py`) con TypedDict/Pydantic.
- [ ] Supervisor: clasificación de intención (modelo barato) y enrutamiento.
- [ ] Integrar RAG Agent, Data Agent, Action Agent como nodos.
- [ ] Agente Crítico (reflection): evalúa respuesta, puede pedir reintento (loop con límite).
- [ ] Checkpointing de LangGraph (persistencia de estado, threads por conversación).
- [ ] Visualizar el grafo (mermaid/ascii).
- **Aprendizajes**: LangGraph, patrones supervisor/worker, reflection, state machines.

### 🔲 Fase 5 — Seguridad (3-4 días)
- [ ] Input guard: heurísticas (patrones conocidos) + clasificador LLM de prompt injection.
- [ ] Output guard: PII redaction (regex + NER), detección de jailbreak exitoso.
- [ ] RBAC: permisos de herramientas por rol de usuario (empleado/admin).
- [ ] Sandboxing SQL: allowlist estricta, límites de filas.
- [ ] Rate limiting por usuario.
- [ ] Comparar implementación propia vs LLM Guard.
- **Aprendizajes**: OWASP LLM Top 10, prompt injection, defensa en profundidad.

### 🔲 Fase 6 — Human-in-the-Loop (2-3 días)
- [ ] `interrupt` de LangGraph antes de acciones sensibles (ej: crear ticket de alta prioridad, cualquier acción de escritura).
- [ ] Cola de revisión: respuestas con baja confianza del crítico van a aprobación.
- [ ] UI de aprobación (aprobar / rechazar / editar) en Streamlit.
- [ ] Reanudación del grafo tras decisión humana (checkpointing).
- **Aprendizajes**: interrupts, confianza/incertidumbre, diseño de flujos supervisados.

### 🔲 Fase 7 — Evals y Observabilidad (3-4 días)
- [ ] Integrar Langfuse/LangSmith: trace completo de cada ejecución del grafo.
- [ ] Dashboard de costos/latencia por request y por agente.
- [ ] Dataset de evaluación: ~50 casos (por agente + casos adversariales).
- [ ] LLM-as-judge para calidad de respuestas.
- [ ] Métricas RAG con RAGAS: faithfulness, answer relevance, context precision.
- [ ] Evals como gate de CI: correr suite antes de cambios grandes.
- **Aprendizajes**: evaluación sistemática, tracing, regression testing de prompts.

### 🔲 Fase 8 — API, UI y Deploy (3-4 días)
- [ ] FastAPI: endpoints de chat (SSE streaming), aprobaciones HITL, admin.
- [ ] Streamlit UI completa: chat, panel de aprobaciones, dashboard de métricas.
- [ ] Dockerizar (app + Chroma + Langfuse) con docker-compose.
- [ ] README con arquitectura, decisiones y demo.
- **Aprendizajes**: productización, async serving, deployment.

### 🔲 Fase 9 — Red Teaming Final (2 días)
- [ ] Suite de ataques automatizados: direct/indirect prompt injection, jailbreaks, exfiltración vía RAG (documentos envenenados), abuso de tools, SQL injection vía lenguaje natural.
- [ ] Reporte: tasa de éxito de ataques antes/después de defensas.
- [ ] Iterar defensas según resultados.
- **Aprendizajes**: mentalidad adversarial, hardening real.

### 🔲 Extras opcionales (si quieres seguir)
- Memoria long-term semántica por usuario.
- MCP (Model Context Protocol) para exponer tools.
- Fine-tuning ligero de un clasificador de intenciones.
- Migración frontend a React + shadcn/ui.
- Multi-modalidad (análisis de imágenes en tickets).

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
