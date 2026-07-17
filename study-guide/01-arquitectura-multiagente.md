# 1. Arquitectura multi-agente y LangGraph

## Concepto

Un sistema **multi-agente** divide una tarea compleja entre varios componentes especializados
("agentes" o "workers"), cada uno con un rol acotado, en lugar de usar un único LLM gigante que
intente hacer todo. Los patrones más comunes:

- **Supervisor / Router**: un componente (LLM o reglas) clasifica la intención y decide a qué
  worker enviar la tarea. Es el patrón que usa Aegis Desk.
- **Orquestador jerárquico**: un agente "manager" delega en sub-agentes y combina resultados.
- **Swarm / peer-to-peer**: los agentes se pasan el control entre sí sin un supervisor central.
- **ReAct (Reason + Act)**: un solo agente que razona, decide qué tool llamar, observa el
  resultado, y repite hasta responder. No es "multi-agente" per se, es el patrón interno de
  un worker con tools.

**LangGraph** modela estos sistemas como un **grafo dirigido de estados**: nodos = funciones
que reciben y devuelven un `state`, edges = transiciones (fijas o condicionales). Es distinto de
una cadena lineal (LangChain "chain") porque permite **ciclos** (reintentos), **bifurcaciones**
condicionales, y **pausas** (`interrupt()` para HITL).

Por qué usar un grafo en vez de un solo prompt gigante:
- **Separación de responsabilidades**: cada nodo tiene un prompt/tarea acotada → más fácil de
  testear, debuggear y evaluar individualmente.
- **Control determinista del flujo**: las reglas de negocio (RBAC, HITL, reintentos) se
  implementan en código Python en los edges, no dependen de que el LLM "decida bien".
  Este es un principio clave: **usar LLMs para razonamiento, código para control**.
- **Costo/latencia**: puedes usar modelos baratos/rápidos para tareas simples (clasificar) y
  modelos más caros solo donde se necesita razonamiento profundo.

## Cómo está implementado en Aegis Desk

Grafo completo en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/graph.py" />:

```
START -> security -> supervisor -> (rag_agent | data_agent | action_planner | chat_agent)
                                                                    |
                                                              (route_from_worker)
                                                                    v
                                                                 critic
                                                                    |
                                            (route_from_critic: END | retry | hitl_review)
                                                                    v
                                                              hitl_review -> action_executor -> END
```

Piezas clave:

- **`AgentState` (TypedDict)** en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/state.py" />
  es el estado compartido que viaja por todos los nodos: `query`, `role`, `intencion`,
  `respuesta`, `fuentes`, `confidence`, `retries`, `action_plan`, etc. Cada nodo es una función
  `def nodo(state: AgentState) -> dict` que devuelve solo los campos que quiere actualizar
  (LangGraph hace el merge). El campo `messages` usa
  `Annotated[list, add_messages]` — un *reducer* que le dice a LangGraph "no sobreescribas la
  lista, hazle append" (patrón estándar de LangGraph para historiales).

- **Supervisor como router** (<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/supervisor.py" />):
  clasifica `intencion ∈ {rag, datos, accion, chat}` con **structured output** (ver archivo 4).
  Tiene un **fast path por regex** para saludos triviales que evita una llamada a LLM entera
  (optimización de latencia real, medida: "hola" bajó de ~2s a ser casi instantáneo en la
  clasificación).

- **Edges condicionales (`add_conditional_edges`)** son funciones Python normales
  (`route_from_supervisor`, `route_from_worker`, `route_from_planner`, `route_from_hitl`,
  `route_from_critic`) que leen el `state` y devuelven el nombre del siguiente nodo. Aquí es
  donde vive la lógica de negocio determinista: RBAC (`can_access(role, intencion)`), nivel de
  riesgo de una acción (`risk_level == "high"` → HITL), lógica de reintento del crítico.

- **Workers especializados**: `rag_agent` (RAG), `data_agent` (SQL vía ReAct), `action_agent`
  (planner/executor separados, ver archivo 6), `chat_agent` (fallback conversacional).

- **`critic_node`**: un segundo LLM (Groq, más barato/rápido) evalúa la respuesta del worker y
  decide si es suficientemente buena, si debe reintentarse (máx. 2 veces,
  <ref_snippet file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/critic_agent.py" lines="20-20" />)
  o si necesita revisión humana. Este es el patrón **"generator-critic"** (o
  "actor-evaluator"): separar quien genera de quien evalúa reduce sesgos de autoevaluación y
  permite un modelo más barato para el juicio de calidad si el generador ya usó el modelo caro.

- **Checkpointer**: necesario para que `interrupt()` pueda pausar el grafo en
  medio de la ejecución y luego reanudarlo desde el mismo punto con `Command(resume=...)`. Sin
  checkpointer persistente, el estado se perdería al pausar o reiniciar.
  - En producción (`src/api/main.py`) el checkpointer se elige automáticamente:
    `PostgresSaver` (`langgraph-checkpoint-postgres`) cuando `DATABASE_URL` está configurado,
    o `SqliteSaver` como fallback local. `get_graph()` (scripts/tests) sigue usando `MemorySaver`
    por simplicidad.
  - Ver archivo 6 (HITL).

- **`react_agent.py`** es un ejemplo aparte (no está en el grafo principal) que usa
  `create_react_agent` de LangGraph: implementa el ciclo ReAct nativo (LLM decide tool → la
  ejecuta → observa resultado → repite) usando *function calling* del proveedor en vez de
  parsear texto tipo "Thought: ... Action: ...". Es útil para explicar la diferencia entre
  ReAct "clásico" (prompt engineering manual con parsing de texto) y ReAct "moderno" (tool/function
  calling nativo del modelo).

## Preguntas de entrevista

**P: ¿Por qué elegiste una arquitectura multi-agente en vez de un solo agente con muchas tools?**
> Con un solo agente con 10+ tools y lógica de negocio compleja (RBAC, HITL, distintos dominios:
> documentos, SQL, acciones), el prompt se vuelve enorme y frágil, y es difícil auditar por qué
> tomó una decisión. Separando por dominio (RAG/datos/acción/chat) cada worker tiene un prompt
> acotado y testeable de forma aislada, y las reglas de negocio críticas (permisos, HITL) las
> pongo en código Python determinista en los edges del grafo, no dependo de que el LLM decida
> "por las buenas" respetar el RBAC.

**P: ¿Qué diferencia hay entre LangChain y LangGraph, y por qué usaste este último?**
> LangChain es más para cadenas lineales (prompt → LLM → parser). LangGraph modela el flujo como
> grafo de estados con soporte nativo para ciclos (reintentos), branching condicional, y
> `interrupt()` para pausar la ejecución (HITL) con persistencia de estado vía checkpointer. Mi
> flujo tiene loops (crítico pide reintento) y pausas (aprobación humana antes de enviar un
> email), así que necesitaba ese control explícito sobre el estado y las transiciones.

**P: ¿Cómo decides a qué worker enrutar una consulta? ¿Es 100% LLM?**
> No. El supervisor usa un LLM con structured output para clasificar la intención, pero antes
> de eso hay un fast-path por regex para mensajes triviales (saludos) que evita la llamada al
> LLM. Y después de clasificar, el acceso al worker se filtra con RBAC en código determinista
> (`can_access(role, intencion)`) — el LLM no decide permisos, solo intención.

**P: ¿Qué pasa si el crítico nunca está satisfecho? ¿Hay riesgo de loop infinito?**
> No, hay un `MAX_RETRIES = 2` explícito en el estado (`retries`). Si se agotan los reintentos y
> la confianza sigue baja, en vez de reintentar de nuevo se enruta a `hitl_review` para que un
> humano decida. Es un patrón de "circuit breaker" para evitar loops infinitos y costos
> descontrolados de LLM.

**P: ¿Cómo manejas el estado compartido entre agentes sin que se pisen entre sí?**
> LangGraph usa un `TypedDict` (`AgentState`) y cada nodo devuelve un diccionario parcial con
> solo los campos que modifica; LangGraph hace merge automático sobre el estado global. Para
> campos que deben acumularse en vez de sobreescribirse (como `messages`), se usa un *reducer*
> vía `Annotated[list, add_messages]`.
