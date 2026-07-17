# Optimizaciones de Latencia e Infraestructura

## 2026-07-15 — Optimizaciones de latencia

### 1. Fast path en supervisor (regex)
- Saludos/despedidas triviales ("hola", "gracias", "adiós") se clasifican con regex sin llamar al LLM.
- Ahorro: ~3s por mensaje trivial.
- Seguridad: `security_node` filtra prompt injection **antes** del fast path.

### 2. Skip crítico para chat trivial
- Si intención es `chat` y confidence >= 0.9, la respuesta va directo a END sin pasar por el crítico.
- Ahorro: ~3s en respuestas de chat.

### 3. HITL inteligente (solo acciones sensibles)
- **Antes**: todas las acciones (tickets + emails) iban a HITL.
- **Ahora**: solo emails van a aprobación humana.
- Tickets (crear/listar/buscar) pasan directo al usuario.
- Fix: detección de email por verbos de acción ("enviado a", "email enviado") en vez de palabra suelta ("email" aparecía en títulos de tickets).

### 4. Modelo híbrido Groq + DeepInfra
- **Supervisor**: Groq Llama-3.1-8B-Instant (gratis, ~0.4s).
- **Crítico**: Groq Llama-3.3-70b-versatile (gratis, ~0.5s, mejor razonamiento).
- **Workers** (RAG, datos, acción, chat): DeepInfra DeepSeek-V4-Flash (calidad).
- Structured output: `method="function_calling"` (json_schema no soportado en Groq, json_mode no garantiza schema completo).

### 5. Config de Groq
- `src/config.py`: `groq_api_key`, `groq_base_url`, `groq_model`.
- `src/llm/providers.py`: Groq agregado a `PROVIDERS`, `get_fast_llm()` usa Groq por defecto.

### Resultados de latencia

| Consulta | Antes (DeepInfra) | Ahora (Groq + DeepInfra) |
|---|---|---|
| "hola" (fast path) | ~2s | ~2.7s |
| "¿vacaciones?" (RAG) | ~10s | ~8.4s |
| "¿empleados?" (datos) | ~11s | ~3.4s |
| "listar tickets" (acción) | ~7s | ~5.7s |

## 2026-07-16 — Conexión a Supabase y Docker

### 1. Connection Pooler / Supavisor
- El host directo `db.<ref>.supabase.co` solo resuelve por IPv6 en este entorno.
- Se usa el **Connection Pooler** de Supabase (`*.pooler.supabase.com`) para conectividad IPv4 estable.

### 2. Normalización de `DATABASE_URL`
- `src/db/postgres_utils.py` normaliza la URL para soportar passwords con `$`, `@`, `%` y `#`.
- Para Docker Compose se recomienda percent-encodear `$` → `%24`, `@` → `%40`, `%` → `%25` en el archivo `.env`.

### 3. `search_path` y schema `extensions`
- Cada conexión psycopg setea `search_path=public,extensions` para resolver el tipo `vector` cuando la extensión pgvector vive en el schema `extensions`.

### 4. Health check rápido
- `/health` usa `connect_timeout=1s` y reutiliza el estado de la conexión principal para `hitl_queue`.
- Evita que Docker `HEALTHCHECK` (5s timeout) marque el contenedor como `unhealthy` cuando Supabase está lento o bloqueado por rate limit.

## Archivos modificados

- `src/config.py` — config de Groq.
- `src/llm/providers.py` — Groq en PROVIDERS, `get_fast_llm()` con parámetro `model`.
- `src/agents/supervisor.py` — fast path regex + Groq + function_calling.
- `src/agents/critic_agent.py` — Groq llama-3.3-70b + function_calling.
- `src/agents/graph.py` — `route_from_worker` (skip crítico para chat) + HITL solo para emails.
- `src/agents/hitl_node.py` — solo pausa para acciones sensibles (email).
- `src/db/postgres_utils.py` — normalización de URL, `search_path`, pool.
- `src/api/main.py` — health check rápido con timeout.
- `scripts/test_groq.py` — test de latencia Groq vs DeepInfra.
- `scripts/test_groq_api.py` — test de latencia del grafo completo.
- `scripts/test_groq_structured.py` — test de structured output con Groq.

## Pendientes futuros

- Saltar crítico para datos con confidence alta (como ya hacemos con chat).
- Marcar `tool_used` en estado para detección de email más robusta.
- Streaming al frontend (percepción de menor latencia).
- Fast path para "listar tickets" y "buscar ticket" (patrones regex).
