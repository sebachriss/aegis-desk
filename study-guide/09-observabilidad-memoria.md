# 9. Observabilidad, tracing y memoria conversacional

## Concepto

### Observabilidad en sistemas LLM
A diferencia de software tradicional, en sistemas LLM necesitas trazar no solo "qué endpoint se
llamó" sino: qué prompt se envió, qué modelo respondió, cuántos tokens/costo, cuánta latencia,
qué decisión de ruteo se tomó, y — crítico para debugging — **por qué** el sistema tomó ese
camino (qué clasificó el supervisor, qué confidence dio el crítico). Sin esto, depurar por qué
una respuesta salió mal es casi imposible una vez que el sistema tiene varios agentes en cadena.

Dos niveles típicos:
- **Tracing/logging estructurado propio**: cada ejecución se registra como un evento con campos
  fijos (query, intención, respuesta, confidence, fuentes, tiempo, reintentos). Barato, sin
  dependencias externas, buena base para dashboards propios.
- **Plataformas de LLM observability** (LangSmith, Langfuse, Helicone): tracing más rico
  (spans anidados por cada llamada a LLM/tool dentro de una ejecución), comparación de prompts,
  debugging visual — más setup pero mucho más profundo para diagnosticar sistemas complejos.

### Memoria conversacional
- **Corto plazo (in-context)**: mantener los últimos N mensajes de la conversación actual para
  dar contexto al LLM en el siguiente turno, con límite (ventana deslizante) para controlar
  tokens/costo.
- **Largo plazo**: persistir hechos/preferencias del usuario entre sesiones (no implementado
  aquí, pero es lo que seguiría — típicamente con embeddings + un vector store separado del de
  RAG documental, o una base de datos estructurada de "memorias").

## Cómo está implementado en Aegis Desk

- **Tracing JSONL** en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/observability/tracing.py" />:
  `trace_execution()` escribe una línea JSON por ejecución en `data/traces.jsonl` (formato JSON
  Lines: fácil de hacer append sin reescribir el archivo completo, fácil de parsear línea por
  línea, fácil de tail-ear para debugging en vivo). Campos: `query`, `intencion`, `respuesta`,
  `confidence`, `fuentes`, `retries`, `elapsed_seconds`, `user_id`, `role`, `tool_name`,
  `authorization_decision`, `action_plan`, `approved_by`, `approved_at` — es decir, no solo el
  resultado sino toda la decisión de seguridad/autorización que llevó a ese resultado.
- `get_stats()` / `print_stats()`: agregaciones simples sobre los traces — conteo por intención,
  confidence promedio (global y por intención), tiempo promedio, total de reintentos, cuántas
  quedaron bloqueadas. Es la base de datos "cruda" detrás del dashboard de métricas del frontend.
- El módulo documenta explícitamente cómo migrar a **LangSmith** si se necesita algo más
  profundo (setear `LANGSMITH_API_KEY` y `LANGSMITH_TRACING=true` — LangChain autotraza sin
  cambiar código) — es una decisión consciente de empezar simple (JSONL propio, cero
  dependencias/costo) y dejar la puerta abierta a una plataforma dedicada cuando la complejidad
  lo justifique, en vez de sobre-diseñar desde el día uno.
- **`filter_pii()` se aplica antes de guardar en tracing** — un detalle de seguridad importante
  que conecta con el archivo 5: los logs/traces son también una superficie de fuga de datos si no
  se les aplica el mismo filtro que a las respuestas al usuario.

- **Memoria conversacional** en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/memory/short_term.py" />:
  `ChatMemory` con ventana deslizante (`max_messages=20` por defecto). `add_user_message`,
  `add_ai_message`, `add_system_message` van armando `self.messages` en formato LangChain
  (`HumanMessage`, `AIMessage`, `SystemMessage`); `get_messages()` devuelve solo los últimos N.
  Es deliberadamente simple: no hay resumen de mensajes viejos ni memoria persistente entre
  sesiones — solo el turno actual de la conversación.

## Preguntas de entrevista

**P: ¿Cómo depuras por qué un agente tomó una decisión equivocada, en un sistema con varios
nodos en cadena?**
> Cada ejecución completa del grafo queda registrada en `data/traces.jsonl` con la intención
> clasificada por el supervisor, la confidence del crítico, cuántos reintentos hubo, y qué
> decisión de autorización se tomó — así puedo reconstruir el camino exacto que siguió sin tener
> que reproducir la ejecución. Para debugging más profundo en desarrollo, tengo un CLI interactivo
> (`scripts/cli_chat.py`) para reproducir un caso puntual con logs en vivo.

**P: ¿Por qué JSONL para tracing y no una base de datos desde el día uno?**
> Porque para el volumen y las necesidades del proyecto (analizarlo yo mismo, alimentar un
> dashboard simple), un append-only log en JSON Lines es suficiente, gratis, y no requiere
> infraestructura adicional. Diseñé el módulo para que migrar a LangSmith (o a una DB real) sea
> un cambio de configuración, no una reescritura — dejo la puerta abierta sin pagar el costo de
> complejidad hasta que realmente lo necesite.

**P: ¿Cómo evitas que tus logs/traces se conviertan en una fuga de datos sensibles?**
> Aplico el mismo filtro de PII que uso en las respuestas al usuario, ANTES de escribir el trace
> — el principio es que cualquier punto de persistencia (no solo la respuesta visible al usuario)
> es una superficie de exposición de datos y debe pasar por el mismo guardrail.

**P: ¿Cómo maneja tu sistema la memoria conversacional y qué limitación tiene ese enfoque?**
> Uso una ventana deslizante de los últimos N mensajes (`ChatMemory`), lo cual controla tokens y
> evita exceder la ventana de contexto del modelo, pero significa que información relevante de
> hace muchos turnos se pierde sin más. La mejora natural sería resumir mensajes viejos en vez de
> descartarlos directamente, o tener memoria de largo plazo persistida entre sesiones — ninguna
> de las dos está implementada actualmente, es una limitación consciente del proyecto en su
> etapa actual.
