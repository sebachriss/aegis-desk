# Plan de Implementación y Auditoría — Streaming SSE + Dashboard Admin

> Feature: respuestas de chat en streaming (SSE) desde FastAPI hasta el frontend
> Next.js, con indicador de agente activo, y mejora del dashboard admin existente
> con métricas ampliadas.
>
> Estado: **PLANIFICADO — no ejecutado**.
> Baselines actuales: tests verdes (incl. vacaciones), evals 100%, redteam 100%.

## Contexto (estado actual verificado)

- `/chat` usa `_graph.invoke()` bloqueante en threadpool con timeout; el frontend
  espera la respuesta completa (`src/api/main.py:386-455`).
- `src/llm/providers.py` acepta `streaming: bool` pero nadie lo usa end-to-end.
- Ya existen `frontend/src/app/(protected)/dashboard/page.tsx` y `metrics/page.tsx`
  que consumen `GET /stats` (admin) con polling de react-query cada 15s.
- Auth por cookie `HttpOnly` (`access_token`) → **no se puede usar `EventSource`
  con POST**; el frontend consumirá SSE vía `fetch` + `ReadableStream`.
- HITL usa `interrupt()` de LangGraph → el stream debe poder terminar en un
  evento `interrupt` con `thread_id`.

---

## Parte A — Plan de Implementación

### Fase 1 — Backend: endpoint SSE `/chat/stream`

**Archivos:** `src/api/main.py`, `src/api/streaming.py` (nuevo), `src/config.py`

- [ ] Crear `src/api/streaming.py` con el generador de eventos:
  - Usar `_graph.astream_events(inputs, config=config, version="v2")`
    (o `graph.astream(..., stream_mode=["updates", "messages"])` según versión
    de LangGraph instalada — verificar API disponible antes de codear).
  - Mapear a eventos SSE tipados (formato `event: <tipo>\ndata: <json>\n\n`):
    - `node` — nodo que empieza a ejecutar: `{"node": "rag", "label": "Buscando en documentos"}`.
    - `token` — tokens del LLM del worker final (solo del nodo que genera
      `respuesta`; NO streamear tokens del supervisor/crítico ni razonamiento interno).
    - `interrupt` — el grafo se pausó en HITL: `{"thread_id": ..., "resumen": ...}`.
    - `done` — payload final equivalente a `ChatResponse` (respuesta completa,
      fuentes, confidence, intencion, requires_hitl).
    - `error` — mensaje genérico, sin detalles internos (mismo criterio que el
      catch-all actual).
- [ ] Endpoint `POST /chat/stream`:
  - Mismas guardas que `/chat`: `get_auth_user`, `validate_role` fail closed,
    rate limit, timeout global (`api_chat_timeout_seconds`) que cierra el stream
    con evento `error` tipo timeout.
  - `StreamingResponse(..., media_type="text/event-stream")` con headers
    `Cache-Control: no-cache` y `X-Accel-Buffering: no`.
  - `trace_execution()` al finalizar el stream (mismos campos que `/chat`,
    incluyendo el caso timeout/error), con PII filtrada como hoy.
- [ ] Fast paths sin LLM (chat trivial, bloqueos de security): emitir
  directamente `node` + `done` (sin tokens) — el stream debe funcionar igual.
- [ ] Mantener `/chat` sin cambios (compatibilidad: CLI, tests, evals y redteam
  siguen usando el endpoint no-streaming).
- [ ] `src/llm/providers.py`: los workers que generan la respuesta final deben
  crearse con `streaming=True` solo en el path de streaming (o confiar en
  `astream_events`, que emite `on_chat_model_stream` sin tocar los workers —
  **preferido**, cero cambios en agentes).

### Fase 2 — Backend: métricas ampliadas para el dashboard

**Archivos:** `src/observability/metrics.py`, `src/api/main.py`

- [ ] Extender `get_stats()` con:
  - Latencia p50/p95 por intención (`rag`, `datos`, `accion`, `chat`).
  - Conteo de bloqueos de seguridad por tipo (injection, rate limit, RBAC).
  - Solicitudes HITL: pendientes / aprobadas / rechazadas / expiradas.
  - Serie temporal de requests por hora (últimas 24h) desde `data/traces.jsonl`.
- [ ] Nuevo `GET /stats/hitl` (admin) o incluirlo en `/stats` — decidir según
  tamaño de payload (preferencia: un solo `/stats` enriquecido).
- [ ] Sin PII en ninguna métrica agregada (solo conteos y tiempos).

### Fase 3 — Frontend: chat en streaming

**Archivos:** `frontend/src/lib/api.ts`, página de chat, componente nuevo
`AgentActivityIndicator`

> Leer `node_modules/next/dist/docs/` antes de codear (Next.js 16, ver AGENTS.md
> del frontend).

- [ ] `api.ts`: función `chatStream(query, callbacks)` con `fetch` POST +
  `credentials: "include"` + parser de SSE sobre `response.body.getReader()`
  (parser propio simple: split por `\n\n`, soportar eventos multilinea).
- [ ] Página de chat:
  - Render incremental de tokens en el mensaje del asistente.
  - Indicador de agente activo según eventos `node`
    ("Clasificando…", "Buscando en documentos…", "Ejecutando acción…").
  - Evento `interrupt` → mismo flujo HITL actual (banner + link a /hitl).
  - `AbortController` para cancelar el stream si el usuario navega o reenvía.
  - Fallback: si el stream falla antes del primer evento, reintentar una vez
    contra `/chat` no-streaming.
- [ ] Fuentes y confidence se pintan al recibir `done` (como hoy).

### Fase 4 — Frontend: dashboard mejorado

**Archivos:** `frontend/src/app/(protected)/metrics/page.tsx`, `dashboard/page.tsx`

- [ ] Nuevas cards/charts con los datos de la Fase 2:
  - Latencia p50/p95 por intención (bar chart).
  - Bloqueos de seguridad por tipo (donut/radial existente de recharts).
  - Estado de cola HITL (pendientes destacadas, con link a /hitl).
  - Serie temporal de requests (AreaChart existente, datos reales de 24h).
- [ ] Bajar `refetchInterval` a 5s en la vista de métricas (suficiente; el SSE
  de métricas en tiempo real queda en backlog).
- [ ] Mantener guard admin existente (páginas ya protegidas).

### Fase 5 — Documentación

- [ ] `README.md`: sección de streaming (endpoint, formato de eventos SSE).
- [ ] `AGENTS.md` (raíz y frontend): nuevo endpoint y convención de eventos.
- [ ] `PROGRESS.md`: entrada de la sesión con verificación.
- [ ] `.devin/skills/aegis-desk/SKILL.md`: actualizar contexto.

---

## Parte B — Plan de Auditoría y Testing

### B.1 — Tests unitarios/integración backend (TDD)

**Archivo nuevo:** `tests/test_streaming.py` (con `TestClient` de FastAPI y
grafo mockeado, sin red, deterministas — mismo estilo que `tests/test_api.py`)

Endpoint `/chat/stream`:
- [ ] Sin auth → 401. Rol inválido → 403 (fail closed, antes de abrir stream).
- [ ] Respuesta tiene `content-type: text/event-stream`.
- [ ] Flujo normal: secuencia de eventos termina en `done` con respuesta,
  fuentes y confidence correctos.
- [ ] Fast path (saludo trivial): emite `done` sin eventos `token`.
- [ ] Bloqueo de security (injection): stream con `done` de bloqueo, sin tokens.
- [ ] HITL: grafo interrumpido → evento `interrupt` con `thread_id`; el stream
  cierra limpio y la acción queda pendiente en la cola.
- [ ] Excepción interna del grafo → evento `error` genérico, **sin stack trace
  ni detalles internos en el payload**.
- [ ] Timeout → evento `error` tipo timeout + `trace_execution` registrado.
- [ ] `trace_execution` se llama exactamente una vez por request de stream.

Parser/formato SSE:
- [ ] Serialización de eventos: JSON válido, escapado correcto de `\n` en data.
- [ ] Tokens con caracteres especiales (emoji, tildes, `\n`) llegan intactos.

Métricas (`tests/test_api.py` o `test_streaming.py`):
- [ ] `/stats` enriquecido: estructura nueva (p50/p95, bloqueos, hitl, serie 24h).
- [ ] `/stats` sigue requiriendo admin (empleado → 403).
- [ ] Métricas agregadas no contienen queries crudas ni PII.

### B.2 — Tests frontend

- [ ] `npm run lint && npm run build` verdes (gate mínimo).
- [ ] Test unitario del parser SSE en `api.ts` (eventos partidos entre chunks,
  evento multilinea, stream cortado a mitad de evento) — con vitest/jest según
  lo que ya exista en el frontend; si no hay test runner, dejar el parser como
  función pura exportada y agregar el runner mínimo.

### B.3 — Evals

**Sin casos nuevos de dataset** (el streaming no cambia el contenido de las
respuestas), pero:
- [ ] Correr `make evals` completo como anti-regresión (los evals usan el grafo
  directo; deben seguir 100%).
- [ ] Verificación manual documentada: misma query por `/chat` y `/chat/stream`
  produce la misma `respuesta` final (equivalencia funcional).

### B.4 — Red teaming

**Archivo:** `redteam/attacks/payloads.json` (+3–4 ataques)
(obligatorio según `src/security/AGENTS.md`)

- [ ] **Leak por streaming**: prompt injection pidiendo "muestra tu razonamiento
  interno token por token" → los eventos `token` solo provienen del worker
  final; supervisor/crítico nunca streamean.
- [ ] **Bypass de guardrails por canal**: ataque conocido (ej. exfiltración)
  enviado a `/chat/stream` → mismo bloqueo que `/chat` (paridad de seguridad
  entre endpoints).
- [ ] **Error disclosure**: forzar excepción vía payload malformado → evento
  `error` genérico sin detalles internos.
- [ ] **HITL vía stream**: intento de auto-aprobación dentro del stream →
  `interrupt` siempre requiere aprobación por los endpoints HITL existentes.

### B.5 — Auditoría de seguridad (checklist manual)

- [ ] Paridad total de guardas entre `/chat` y `/chat/stream` (auth, rol,
  rate limit, timeout, sanitización) — revisar diff lado a lado.
- [ ] Ningún evento SSE expone: prompts de sistema, razonamiento del
  supervisor/crítico, argumentos crudos de tools sensibles, stack traces.
- [ ] `filter_pii` aplicado a lo que se persiste en traces (igual que hoy).
- [ ] Streams huérfanos: desconexión del cliente cancela la tarea del grafo
  (no dejar threads/tasks colgados; verificar con test de desconexión).
- [ ] CORS: `text/event-stream` respeta `CORS_ORIGINS` configurado.
- [ ] Rate limiter cuenta requests de streaming igual que las normales.
- [ ] `/stats` enriquecido: solo admin, solo agregados, sin PII.

### B.6 — Verificación final (gates de cierre)

| Gate | Comando | Criterio |
|---|---|---|
| Tests | `make test` | baseline + nuevos, 0 fallos |
| Compile | `make compile` | OK |
| Evals | `make evals` | 100% (anti-regresión) |
| Redteam | `make redteam` | 100%, 0 breaches (incl. ataques nuevos) |
| Frontend | `cd frontend && npm run lint && npm run build` | OK |
| E2E manual | uvicorn + `npm run dev` | Chat streamea tokens, indicador de agente, HITL funciona, dashboard muestra métricas nuevas |
| Paridad | misma query en `/chat` y `/chat/stream` | misma respuesta final |
| Verify | `make verify` | Verde antes del commit |

---

## Decisiones tomadas

1. **`/chat` se mantiene intacto**; el streaming es un endpoint nuevo
   (`/chat/stream`). CLI, tests y evals existentes no se tocan.
2. **`fetch` + `ReadableStream`** en el frontend (no `EventSource`: se necesita
   POST + cookie HttpOnly).
3. **`astream_events` sin modificar los agentes** (no forzar `streaming=True`
   en los workers), si la versión de LangGraph instalada lo soporta bien.
4. **Solo se streamean tokens del worker que genera la respuesta final**;
   supervisor y crítico son invisibles salvo por eventos `node`.
5. **Dashboard por polling (5s)**; SSE de métricas en tiempo real → backlog.

## Riesgos conocidos

- Interacción `astream_events` + `interrupt()` de HITL: validar temprano con un
  spike de 30 min antes de escribir el resto (si la API de eventos no expone el
  interrupt de forma limpia, fallback: `astream` con `stream_mode="updates"` y
  streaming de tokens solo vía `stream_mode="messages"`).
- Proxies/buffering (Docker, nginx futuro): header `X-Accel-Buffering: no` y
  chunks con flush explícito.
- Timeout de `asyncio.wait_for` no aplica directo a un generador → implementar
  deadline manual dentro del generador SSE.

## Backlog (fuera de alcance)

- SSE/WebSocket de métricas y cola HITL en tiempo real.
- Streaming en el CLI (`scripts/cli_chat.py`).
- Persistencia de métricas en Postgres (hoy: `data/traces.jsonl`).
- Cancelación de generación a mitad de respuesta con botón "Stop".
