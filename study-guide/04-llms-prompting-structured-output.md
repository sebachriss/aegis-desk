# 4. LLMs: proveedores, prompting, structured output, function calling, latencia/costo

## Concepto

### Structured output / function calling
Los LLMs modernos pueden devolver respuestas que cumplen un **schema** (JSON Schema, Pydantic)
en vez de texto libre. Hay dos mecanismos comunes:
- **Function/tool calling nativo**: el proveedor entrena el modelo para "elegir" invocar una
  función con argumentos en JSON que cumplen un schema declarado. Es lo que usa LangChain por
  debajo cuando llamas `.with_structured_output(Schema, method="function_calling")`.
- **JSON mode / grammar-constrained decoding**: se restringe el proceso de generación de tokens
  para que solo pueda producir tokens válidos según una grammar/schema (más estricto, no todos
  los proveedores lo soportan igual).

Structured output es crítico en sistemas multi-agente porque el código downstream (edges del
grafo, RBAC, routing) necesita campos confiables (`intencion: Literal[...]`, `confidence: float`)
en vez de tener que parsear texto libre con regex (frágil).

### Prompting
- **System prompt**: define rol, reglas, formato de salida — es el "contrato" de comportamiento.
- **Few-shot**: dar ejemplos dentro del prompt para guiar el formato/estilo de respuesta.
- **Grounding**: instruir al modelo a basarse solo en información dada (contexto RAG) y no usar
  conocimiento externo — reduce alucinaciones.
- **Temperature**: controla aleatoriedad en el muestreo de tokens. `temperature=0` → casi
  determinista, ideal para clasificación, extracción, RAG factual. `temperature` más alta → más
  variedad, útil para generación creativa.

### Modelo híbrido / latencia y costo
En sistemas de producción reales, no todos los nodos de un pipeline necesitan el modelo más
potente (y más caro/lento). Un patrón común es usar modelos rápidos/baratos para tareas de bajo
razonamiento (clasificación, extracción simple) y modelos más capaces solo donde hace falta
razonamiento profundo (generación de la respuesta final).

Proveedores de inferencia rápida como **Groq** usan hardware especializado (LPUs, no GPUs) para
lograr latencias muy bajas en modelos open-weight (Llama, etc.), a menudo con tiers gratuitos —
ideales para nodos de control (supervisor, crítico) donde la latencia importa más que la máxima
calidad de razonamiento.

## Cómo está implementado en Aegis Desk

- **Abstracción multi-proveedor** en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/llm/providers.py" />:
  `get_llm(provider, model, temperature, max_tokens, streaming)` crea un `ChatOpenAI` de
  LangChain configurado con `base_url` distinto según proveedor (DeepInfra o Groq). Esto
  funciona porque ambos proveedores exponen una **API compatible con el formato OpenAI**
  (patrón muy común en el ecosistema: cualquier proveedor que implemente el mismo contrato HTTP
  puede reusar el mismo cliente `ChatOpenAI`, sin SDKs custom).
- **`get_fast_llm(provider="groq", ...)`**: wrapper específico para los nodos "de control"
  (supervisor, crítico) — `temperature=0`, `max_tokens=256` (solo necesitan devolver JSON chico).
- **Modelo híbrido de latencia** (ver `README.md` del proyecto):

  | Nodo | Modelo | Provider | Latencia aprox. |
  |---|---|---|---|
  | Supervisor | Llama-3.1-8B-Instant | Groq (free) | ~0.4s |
  | Crítico | Llama-3.3-70b-versatile | Groq (free) | ~0.5s |
  | RAG / Data / Action / Chat (workers) | DeepSeek-V4-Flash | DeepInfra | ~3-5s |

  Razonamiento: supervisor y crítico son tareas de **clasificación/evaluación** (poco
  razonamiento profundo, output corto) → van en el proveedor más rápido. Los workers necesitan
  generar respuestas completas y a veces razonar sobre múltiples tools → van en un modelo más
  capaz aunque más lento.

- **Fast path sin LLM**: el supervisor detecta saludos triviales por regex
  (<ref_snippet file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/supervisor.py" lines="23-37" />)
  y evita la llamada al LLM completamente para esos casos — la optimización más barata posible
  (latencia cero de LLM) para el caso más frecuente y trivial ("hola", "gracias").

- **Structured output** usado en todo el proyecto:
  - Supervisor → `ClasificacionSupervisor(intencion: Literal[...], confidence: float)`.
  - Crítico → `EvaluacionCritico(confidence, razon, necesita_reintento)`.
  - Action planner → `ActionPlan(tool_name, arguments, reasoning)`
    (<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/action_agent.py" />).
  - Evals/judge → `EvaluacionJuez(score, razon, categoria)`.
  Todos usan `llm.with_structured_output(Schema, method="function_calling")` — es decir, se
  apoyan en tool/function calling del proveedor, no en pedir "responde en JSON" y parsear a mano
  (mucho más frágil, propenso a que el modelo agregue texto antes/después del JSON).

- **Memoria conversacional** (`ChatMemory`, ver archivo 9): ventana deslizante de últimos N
  mensajes — otra técnica de control de costo/latencia (no mandas todo el historial infinito al
  LLM en cada turno, lo cual además puede exceder la ventana de contexto del modelo).

## Preguntas de entrevista

**P: ¿Cómo garantizas que el LLM devuelva datos en el formato que tu código necesita?**
> Uso structured output vía `with_structured_output()` de LangChain, que internamente usa
> function/tool calling del proveedor: declaro un modelo Pydantic (ej. `ClasificacionSupervisor`
> con `intencion: Literal["rag","datos","accion","chat"]`) y el LLM es forzado a devolver
> argumentos que cumplen ese schema. Es mucho más confiable que pedir "responde en JSON" en el
> prompt y parsear con `json.loads()`, porque no depende de que el modelo no agregue texto
> extra o rompa el formato.

**P: ¿Por qué usar dos proveedores de LLM distintos (Groq y DeepInfra) en el mismo sistema?**
> Por latencia y costo, alineado a la complejidad de la tarea de cada nodo. El supervisor solo
> clasifica una intención (4 categorías) y el crítico solo evalúa una respuesta — son tareas de
> bajo razonamiento con output corto, así que van en Groq, que usa LPUs y es ~10x más rápido que
> GPU para modelos open-weight, con tier gratuito. Los workers necesitan generar respuestas
> completas y razonar con tools, así que usan un modelo más capaz en DeepInfra aunque sea más
> lento. Es la misma lógica de "no uses un modelo caro donde uno barato basta", aplicada a nivel
> de arquitectura, no solo de prompt.

**P: ¿Qué es `temperature=0` y cuándo lo usas?**
> Reduce la aleatoriedad del muestreo de tokens, haciendo la salida casi determinista. Lo uso en
> clasificación (supervisor), evaluación (crítico), extracción de argumentos (action planner), y
> RAG factual — todos casos donde quiero consistencia y fidelidad, no creatividad.

**P: ¿Cómo evitas mandar todo el historial de la conversación en cada llamada?**
> Con una ventana deslizante en `ChatMemory` que devuelve solo los últimos N mensajes
> (`max_messages`). Esto controla tokens/costo y evita exceder la ventana de contexto del
> modelo en conversaciones largas. Un sistema más avanzado podría además resumir mensajes viejos
> en vez de simplemente descartarlos, para no perder contexto relevante de largo plazo.

**P: ¿Qué pasa si el proveedor de LLM falla o da timeout? ¿Tienes fallback?**
> Ahora mismo no hay fallback automático entre proveedores (es una limitación conocida del
> proyecto) — es algo que agregaría en un sistema de producción real: reintentos con backoff,
> y potencialmente un segundo proveedor como fallback si el primario falla, dado que ya tengo la
> abstracción de `PROVIDERS` que hace ese swap relativamente sencillo de implementar.
