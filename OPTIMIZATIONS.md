# Optimizaciones de Latencia — Sesión 2025-07-15

## Cambios implementados

### 1. Fast path en supervisor (regex)
- Saludos/despedidas triviales ("hola", "gracias", "adiós") se clasifican con regex sin llamar al LLM
- Ahorro: ~3s por mensaje trivial
- Seguridad: `security_node` filtra prompt injection **antes** del fast path

### 2. Skip crítico para chat trivial
- Si intención es `chat` y confidence >= 0.9, la respuesta va directo a END sin pasar por el crítico
- Ahorro: ~3s en respuestas de chat

### 3. HITL inteligente (solo acciones sensibles)
- **Antes**: todas las acciones (tickets + emails) iban a HITL
- **Ahora**: solo emails van a aprobación humana
- Tickets (crear/listar/buscar) pasan directo al usuario
- Fix: detección de email por verbos de acción ("enviado a", "email enviado") en vez de palabra suelta ("email" aparecía en títulos de tickets)

### 4. Modelo híbrido Groq + DeepInfra
- **Supervisor**: Groq Llama-3.1-8B-Instant (gratis, ~0.4s)
- **Crítico**: Groq Llama-3.3-70b-versatile (gratis, ~0.5s, mejor razonamiento)
- **Workers** (RAG, datos, acción, chat): DeepInfra DeepSeek-V4-Flash (calidad)
- Structured output: `method="function_calling"` (json_mode no soporta schema completo en Groq)

### 5. Config de Groq
- `src/config.py`: `groq_api_key`, `groq_base_url`, `groq_model`
- `src/llm/providers.py`: Groq agregado a `PROVIDERS`, `get_fast_llm()` usa Groq por defecto

## Resultados de latencia

| Consulta | Antes (DeepInfra) | Ahora (Groq + DeepInfra) |
|---|---|---|
| "hola" (fast path) | ~2s | ~2.7s |
| "¿vacaciones?" (RAG) | ~10s | ~8.4s |
| "¿empleados?" (datos) | ~11s | ~3.4s |
| "listar tickets" (acción) | ~7s | ~5.7s |

## Archivos modificados

- `src/config.py` — config de Groq (api_key, base_url, model)
- `src/llm/providers.py` — Groq en PROVIDERS, `get_fast_llm()` con parámetro `model`
- `src/agents/supervisor.py` — fast path regex + Groq + function_calling
- `src/agents/critic_agent.py` — Groq llama-3.3-70b + function_calling
- `src/agents/graph.py` — `route_from_worker` (skip crítico para chat) + HITL solo para emails
- `src/agents/hitl_node.py` — solo pausa para acciones sensibles (email)
- `scripts/test_groq.py` — test de latencia Groq vs DeepInfra
- `scripts/test_groq_api.py` — test de latencia del grafo completo
- `scripts/test_groq_structured.py` — test de structured output con Groq

## Pendiente

### Tests
- [ ] Correr evals (33 casos) con modelo híbrido
- [ ] Correr red team (31 ataques) con modelo híbrido
- [ ] Verificar que no haya regresiones

### Optimizaciones de latencia
- [ ] Saltar crítico para datos con confidence alta (como ya hacemos con chat)
- [ ] Marcar `tool_used` en estado para detección de email más robusta
- [ ] Streaming al frontend (percepción de menor latencia)
- [ ] Fast path para "listar tickets" y "buscar ticket" (patrones regex)

### Migración a la nube
- [ ] **Supabase** (auth + PostgreSQL) — resuelve tickets compartidos entre usuarios
- [ ] **Pinecone** (vector DB) — RAG en la nube
- [ ] **Render** (API deploy, free tier)
- [ ] **Vercel** (frontend deploy, free tier)
- [ ] Variables de entorno: `SUPABASE_URL`, `SUPABASE_KEY`, `PINECONE_API_KEY`

### Stack final target
| Componente | Servicio | Costo |
|---|---|---|
| LLM (workers) | DeepInfra DeepSeek | ~$10 ya pagados |
| LLM (supervisor/crítico) | Groq Llama-3.1/3.3 | Free tier |
| Auth + DB | Supabase | Free tier |
| Vector DB | Pinecone | Free tier |
| API | Render | Free tier |
| Frontend | Vercel | Free tier |
