# 11. Preguntas generales de entrevista ("cuéntame de un proyecto", trade-offs)

Estas son preguntas más abiertas que un entrevistador de AI Engineering suele hacer para evaluar
criterio de diseño, no solo conocimiento de conceptos. Practica contarlas como historia (situación
→ decisión → resultado/aprendizaje), no como lista de features.

## "Cuéntame sobre un proyecto de IA que hayas construido"

> Estructura sugerida (usa tus propias palabras, esto es un esqueleto):
> "Construí Aegis Desk, una plataforma de soporte interno multi-agente para una empresa ficticia.
> El objetivo era aprender de punta a punta cómo se construye un sistema de IA de producción real:
> no solo 'llamar a un LLM', sino resolver RAG, orquestación multi-agente con LangGraph,
> seguridad (RBAC, prompt injection, PII), human-in-the-loop para acciones sensibles, evals, y
> red teaming. El sistema clasifica la intención del usuario (documentos, datos, acciones,
> chat) y la enruta a un worker especializado, con un crítico que evalúa la calidad y decide si
> reintentar o escalar a un humano. La parte que más me enseñó fue implementar seguridad
> real — al principio el HITL se activaba por frases del LLM en la respuesta ('voy a enviar un
> email'), lo cual significaba que el efecto de lado ya podía haber ocurrido antes de la
> aprobación. Lo rediseñé separando planificación de ejecución para que la aprobación humana
> ocurra ANTES de cualquier efecto de lado, con un plan estructurado que no depende de parsear
> texto del LLM."

## Preguntas de trade-offs y criterio de diseño

**P: Si tuvieras que escalar este sistema a 10,000 usuarios concurrentes, ¿qué cambiarías
primero?**
> El rate limiter sigue siendo en memoria por proceso, así que lo reemplazaría por Redis para
> multi-instancia. El checkpointer (`PostgresSaver`) y la cola HITL (`src/db/hitl_queue.py`) ya
> pueden persistir en **Supabase/Postgres** cuando `DATABASE_URL` está set, por lo que las
> conversaciones pausadas sobreviven reinicios y se retoman desde cualquier instancia. El vector
> store por defecto en producción es **Supabase pgvector** (`src/db/supabase_vector.py`), con
> Chroma/Pinecone como fallback; para 10k concurrentes seguiría usando el pooler de Supabase y
> evaluaría añadir re-ranking o hybrid search antes de saltar a otro proveedor.

**P: ¿Cuál fue la decisión de diseño más difícil o de la que aprendiste más?**
> Separar `action_planner` de `action_executor` para arreglar el HITL. Al principio la detección
> de "esto necesita aprobación humana" dependía de que el crítico detectara ciertas frases en la
> respuesta del LLM (ej. "voy a enviar un email a..."), lo cual es frágil (depende de que el LLM
> use exactamente ese lenguaje) y, peor, en algunos flujos la tool ya se había ejecutado antes de
> llegar al crítico. Rediseñarlo como un plan estructurado con `risk_level` determinado por
> reglas de negocio en código (no por el LLM) resolvió ambos problemas a la vez: ya no depende de
> lenguaje natural, y la aprobación ocurre estructuralmente antes de la ejecución, no después.

**P: ¿Qué harías distinto si empezaras de nuevo?**
> Diseñaría el `AgentState` y el flujo planner/executor desde el día uno, en vez de llegar a esa
> arquitectura de forma iterativa después de encontrar el problema de HITL post-facto. También
> partiría con Supabase/Postgres (pgvector, `PostgresSaver`, cola HITL, RLS, `vector` en el schema
> `extensions`) en vez de migrar desde SQLite/Chroma en memoria, y mantendría `filter_pii()`
> aplicado uniformemente a traces y logs.

**P: ¿Cómo mides si tu sistema realmente mejoró después de un cambio (ej. cambiar de modelo)?**
> Con la suite de evals (33 casos, LLM-as-judge) y la suite de red team (31 payloads) como
> regression tests — las corro antes y después de cualquier cambio de modelo o prompt. Cuando
> migré a un modelo híbrido (Groq para supervisor/crítico, DeepInfra para workers) comparé
> latencia por tipo de query (ej. "hola" de ~2s a casi instantáneo, queries de datos de ~11s a
> ~3.4s) además de confirmar que el pass rate de evals y el defense rate de red team no
> bajaran — un cambio de latencia que rompiera calidad o seguridad no sería una mejora real.

**P: ¿Qué es lo que NO está resuelto o es una limitación conocida de tu sistema?**
> (Practica decir esto con confianza — mostrar que conoces los límites de tu propio sistema es
> una señal de madurez, no de debilidad.)
> - El rate limiter sigue en memoria por proceso; no escala multi-instancia sin Redis.
> - Detección de prompt injection es regex, no un clasificador de ML — tiene falsos negativos
>   ante ataques más sofisticados; lo mitigo con RBAC y HITL como capas independientes, no
>   dependo solo de esa detección.
> - No hay fallback automático entre proveedores de LLM si uno falla.
> - RAG usa retrieval vectorial puro (sin hybrid search ni re-ranking); pgvector lo resuelve en
>   producción, pero le faltaría BM25/re-ranking para IDs/nombres propios poco comunes.
> - No hay memoria de largo plazo entre sesiones, solo ventana deslizante de la conversación
>   actual.

## Preguntas rápidas de definición (calienta antes de la entrevista)

- **RAG**: recuperar contexto relevante de una fuente externa y pasárselo al LLM en el prompt,
  en vez de depender de su conocimiento paramétrico.
- **Embedding**: vector numérico que representa el significado semántico de un texto.
- **Function/tool calling**: mecanismo para que el LLM devuelva una llamada estructurada
  (nombre + argumentos JSON) en vez de texto libre.
- **RBAC**: control de acceso basado en el rol del usuario, no en identidad individual.
- **HITL**: pausar la ejecución automática para aprobación humana antes de un efecto de lado.
- **LLM-as-judge**: usar un LLM para evaluar la calidad de la salida de otro sistema/LLM.
- **Prompt injection**: intento de hacer que el modelo ignore sus instrucciones originales vía
  el input (directo) o datos externos que consume (indirecto).
- **Defense-in-depth**: apilar múltiples capas de seguridad independientes, sin asumir que una
  sola es suficiente.
- **Fail-closed**: denegar acceso por defecto ante ambigüedad o error, en vez de permitir.
- **LoRA/QLoRA**: técnicas de fine-tuning eficiente que entrenan solo una fracción pequeña de
  parámetros adicionales, congelando el modelo base.
- **Checkpointer (LangGraph)**: mecanismo de persistencia de estado que permite pausar/reanudar
  un grafo (necesario para HITL).
- **Faithfulness (RAG)**: si la respuesta está respaldada por las fuentes recuperadas, o alucina.
