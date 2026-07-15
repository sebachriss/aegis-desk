# Aegis Desk

> Plataforma de soporte interno inteligente multi-agente para una empresa ficticia (Aegis Corp).
> Proyecto de aprendizaje integral de AI Engineering: LLMs, RAG, multi-agentes, seguridad, HITL, evals y observabilidad.

---

## ¿Qué hace?

Los empleados de Aegis Corp hacen consultas y un equipo de agentes de IA las resuelve de forma **segura, auditable y con supervisión humana**.

```
"¿Cuántos días de vacaciones tengo?"     → RAG Agent busca en documentos
"Crea un ticket de alta prioridad"       → Action Agent crea ticket → HITL aprueba
"¿Cuántos empleados hay en Ventas?"      → Data Agent consulta SQL
"Hola, ¿qué tal?"                        → Chat Agent responde
```

## Arquitectura

```
Usuario
  │
  ▼
Security (prompt injection + rate limit + RBAC)
  │
  ▼
Supervisor (clasifica intención → enruta)
  │        │         │          │
  ▼        ▼         ▼          ▼
RAG      Data      Action     Chat
(docs)   (SQL)    (tools)    (fallback)
  │        │         │          │
  └────────┴────┬────┴──────────┘
               ▼
         Crítico (evalúa calidad)
               │
      ┌────────┴────────┐
      ▼                 ▼
 Respuesta OK      HITL (interrupt →
 (usuario)         aprobación humana)
```

## Stack

| Capa | Tecnología |
|---|---|
| LLM | DeepInfra — DeepSeek-V4-Flash |
| Framework | LangChain + LangGraph |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2, local) |
| Vector Store | Chroma (persistente local) |
| Base de datos | SQLite |
| Observabilidad | Métricas propias (tokens, costo, latencia) |

## Estructura del proyecto

```
aegis-desk/
├── src/
│   ├── config.py               # Settings con pydantic-settings
│   ├── llm/
│   │   └── providers.py        # get_llm() multi-proveedor
│   ├── memory/
│   │   └── short_term.py       # ChatMemory con ventana deslizante
│   ├── observability/
│   │   └── metrics.py          # track_llm_call (tokens, costo, latencia)
│   ├── rag/
│   │   ├── ingest.py           # Chunking por Markdown headers + Chroma
│   │   ├── retriever.py        # Búsqueda por similitud semántica
│   │   ├── chain.py            # Cadena RAG con citas de fuente
│   │   └── documents/          # Docs ficticios (RRHH, IT, FAQ)
│   ├── tools/
│   │   ├── tickets.py          # @tool: crear/listar/buscar tickets
│   │   ├── email.py            # @tool: enviar email (simulado)
│   │   ├── sql.py              # @tool: SELECT sobre SQLite (allowlist)
│   │   └── registry.py         # Registro central de herramientas
│   ├── agents/
│   │   ├── state.py            # AgentState (TypedDict)
│   │   ├── supervisor.py       # Clasifica intención (Literal)
│   │   ├── rag_agent.py        # Worker RAG
│   │   ├── data_agent.py       # Worker SQL (ReAct)
│   │   ├── action_agent.py     # Worker acciones (ReAct)
│   │   ├── chat_agent.py       # Worker fallback + acceso denegado
│   │   ├── critic_agent.py     # Evalúa respuestas, loop de reintento
│   │   ├── security_node.py    # Guardrails (injection + rate limit)
│   │   ├── hitl_node.py        # Human-in-the-Loop con interrupt()
│   │   ├── react_agent.py      # Agente ReAct standalone (Fase 3)
│   │   └── graph.py            # Grafo LangGraph ensamblado
│   └── security/
│       ├── prompt_injection.py # Detección regex + sanitize
│       ├── rbac.py             # Roles empleado/admin
│       ├── rate_limiter.py     # Ventana deslizante 10 req/60s
│       └── pii_filter.py       # Enmascara emails, teléfonos, DNIs
├── scripts/
│   ├── test_llm.py             # Fase 0: primera llamada
│   ├── test_streaming.py       # Fase 1: streaming
│   ├── test_structured.py      # Fase 1: structured outputs
│   ├── test_memory.py          # Fase 1: memoria conversacional
│   ├── test_metrics.py         # Fase 1: métricas
│   ├── cli_chat.py             # Fase 1: CLI interactivo
│   ├── test_rag.py             # Fase 2: RAG
│   ├── test_agent.py           # Fase 3: tool calling
│   ├── test_multi_agent.py     # Fase 4: multi-agente
│   ├── test_security.py        # Fase 5: seguridad
│   └── test_hitl.py            # Fase 6: HITL
├── data/                       # Chroma DB + SQLite (gitignored)
├── PLAN.md                     # Plan maestro del proyecto
├── PROGRESS.md                 # Bitácora de avance
└── requirements.txt
```

## Setup

```bash
# 1. Clonar
git clone https://github.com/USER/aegis-desk.git
cd aegis-desk

# 2. Virtual env
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar API key
cp .env.example .env
# Editar .env y poner DEEPINFRA_API_KEY=...

# 5. Indexar documentos (RAG)
python -m src.rag.ingest

# 6. Probar
python scripts/test_rag.py        # RAG
python scripts/test_agent.py      # Tool calling
python scripts/test_multi_agent.py # Multi-agente
python scripts/test_security.py   # Seguridad
python scripts/test_hitl.py       # HITL
python scripts/cli_chat.py        # CLI interactivo
```

## Fases del proyecto

| Fase | Descripción | Estado |
|---|---|---|
| 0 | Setup (config, providers, primera llamada) | ✅ |
| 1 | Fundamentos LLM (streaming, structured, memory, metrics, CLI) | ✅ |
| 2 | RAG (Markdown chunking, Chroma, retriever, citas) | ✅ |
| 3 | Tool Calling (tickets, email, SQL, agente ReAct) | ✅ |
| 4 | Multi-Agente (supervisor, 4 workers, crítico, LangGraph) | ✅ |
| 5 | Seguridad (prompt injection, RBAC, rate limit, PII) | ✅ |
| 6 | HITL (interrupt, aprobación/rechazo humano) | ✅ |
| 7 | Evals y Observabilidad | 🔲 En progreso |
| 8 | API, UI y Deploy | 🔲 |
| 9 | Red Teaming Final | 🔲 |

## Aprendizajes clave

- **Chunking por Markdown headers** > chunking por tamaño fijo: preserva secciones semánticamente coherentes
- **`Literal` en Pydantic** fuerza al LLM a elegir entre opciones exactas (no inventa categorías)
- **Especialización de agentes**: un agente con 2 tools específicas > un agente con 10 tools
- **`interrupt()` de LangGraph**: pausa el grafo, guarda estado, espera decisión humana
- **Defense in depth**: prompt injection → RBAC → rate limit → PII filter (múltiples capas)

## Licencia

Proyecto educativo. Sin licencia formal.
