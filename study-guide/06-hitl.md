# 6. Human-in-the-Loop (HITL)

## Concepto

HITL significa pausar la ejecución autónoma de un agente en puntos críticos para que un humano
apruebe, rechace o corrija antes de que ocurra un **efecto de lado (side effect) irreversible**
(enviar un email real, cobrar una tarjeta, borrar un registro). Es una de las mitigaciones más
efectivas contra el hecho de que los LLMs son probabilísticos: no puedes garantizar al 100% que
un agente autónomo nunca va a decidir mal, así que para las acciones de mayor riesgo, insertas un
punto de control humano.

Principios de diseño de un buen HITL:
1. **La aprobación debe ocurrir ANTES del efecto de lado**, no después. Un patrón muy común (y
   defectuoso) es "ejecutar la acción y luego pedir confirmación" — para entonces ya es tarde.
2. **Separar planificación de ejecución** (patrón *plan-then-execute*): un componente decide
   *qué* hacer (genera un plan estructurado) y otro componente distinto lo *ejecuta*, solo si
   está aprobado. Esto hace que la pausa sea un punto natural entre ambos pasos, en vez de tener
   que "interrumpir a mitad de una tool call".
2. **Idempotencia**: si el humano aprueba dos veces por error, o el sistema reintenta tras un
   fallo de red, la acción no debe ejecutarse dos veces (ej. no enviar el mismo email dos veces).
3. **Auditabilidad**: quién aprobó, cuándo, y qué exactamente se aprobó debe quedar registrado.
4. **Fail-safe en la decisión**: si la respuesta del humano no es exactamente "approve", se debe
   tratar como rechazo (no asumir aprobación por defecto ante cualquier cosa ambigua).
5. **Selectividad**: no todo necesita HITL — solo lo de alto riesgo. Meter HITL en todo mata la
   productividad del sistema (todo se vuelve síncrono con espera humana).

En LangGraph esto se implementa con `interrupt()`: pausa la ejecución del grafo en ese nodo y
persiste el estado completo gracias a un **checkpointer**; luego se reanuda con
`Command(resume=valor)` desde el mismo punto exacto.

## Cómo está implementado en Aegis Desk

### Separación planner/executor

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/action_agent.py" />:

- **`action_planner_node`**: valida RBAC, obtiene tools permitidas para el rol, y usa structured
  output (`ActionPlan`) para que el LLM decida **qué tool y con qué argumentos**, pero
  **nunca la ejecuta**. El resultado es un diccionario `action_plan` con: `action_id`,
  `tool_name`, `arguments`, `requested_by`, `role`, `risk_level`, `approval_status`,
  `execution_status`, `idempotency_key`, `executed_at`, `reasoning`.
- `_determine_risk_level(tool_name)`: reglas de negocio explícitas en código —
  `enviar_email` → `high`, `consultar_sql` → `medium`, resto → `low`. Esta clasificación de
  riesgo NO la decide el LLM, es una tabla fija — otra vez el principio de "código para control,
  LLM para razonamiento".
- **`action_executor_node`**: solo ejecuta si `approval_status in ("approved", "not_required")`.
  Antes de ejecutar, **revalida RBAC** (por si el estado fue manipulado entre el plan y la
  ejecución) y checa `execution_status == "succeeded"` para no reejecutar una acción ya
  completada (idempotencia a nivel de aplicación).

### El nodo HITL

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/hitl_node.py" />:

- Si `action_plan.approval_status` ya es `"approved"` o `"rejected"`, no vuelve a pausar — evita
  reabrir una decisión ya tomada.
- Si `execution_status == "succeeded"` o ya tiene `executed_at`, rechaza cualquier nuevo intento
  de aprobación — protección extra contra doble ejecución.
- `_redact_sensitive_args()`: al mostrarle el resumen al revisor humano, oculta el cuerpo/asunto
  completo de un email (solo muestra el destinatario) y cualquier password/token/api_key en los
  argumentos — el revisor ve lo mínimo necesario para decidir, no todo el contenido sensible.
- `decision = interrupt(resumen)`: pausa el grafo. LangGraph serializa el estado completo gracias
  al checkpointer, así que el grafo puede reanudarse exactamente donde se quedó, con `thread_id`
  como identificador de la conversación pausada.
  - En producción (`src/api/main.py`) el checkpointer se elige automáticamente:
    `PostgresSaver` (`langgraph-checkpoint-postgres`) si `DATABASE_URL` está configurado, o
    `SqliteSaver` como fallback local. `get_graph()` (scripts/tests) sigue usando `MemorySaver`
    por simplicidad.
  - La cola HITL también se persiste en **Postgres/Supabase** (`src/db/hitl_queue.py`) cuando
    `DATABASE_URL` está set, con fallback a SQLite local.
- **Validación estricta de la decisión**: `if decision not in ("approve", "reject")` → se trata
  como rechazo automático ("Decisión inválida... Acción rechazada por seguridad"). Esto es
  fail-safe: cualquier cosa que no sea exactamente "approve" NO ejecuta la acción.
- Registra `approved_by` (el `user_id` de quien resolvió el interrupt) y `approved_at`
  (timestamp) en el `action_plan` — auditabilidad.

### Persistencia de la cola HITL

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/db/hitl_queue.py" />:
la cola de aprobaciones (`pending`/`approved`/`rejected`) se guarda en **Postgres/Supabase**
cuando `DATABASE_URL` está configurado, con fallback a SQLite local (`data/hitl_queue.sqlite`).
Esto permite listar, aprobar y auditar pedidos de HITL entre reinicios del servidor y desde
múltiples instancias, sin depender de un checkpointer en memoria.

### Routing del grafo alrededor de HITL

<ref_snippet file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/graph.py" lines="83-105" />:
- `route_from_planner`: si `risk_level == "high"` → va a `hitl_review`; si es `low`/`medium` →
  ejecuta directo (**selectividad**: tickets y consultas de datos no necesitan aprobación
  humana, solo emails).
- `route_from_hitl`: si `approval_status == "approved"` → `action_executor`; cualquier otra cosa
  → `END` (la respuesta de rechazo ya se generó en el propio `hitl_node`).
- El crítico también puede forzar HITL (`requires_human_review=True`) cuando la confianza es baja
  y se agotaron los reintentos — un segundo camino hacia revisión humana, no solo por riesgo de
  la acción sino también por baja calidad de la respuesta.

## Preguntas de entrevista

**P: ¿Cómo diseñaste el HITL para que la aprobación ocurra ANTES del efecto de lado?**
> Separé el flujo en `action_planner_node` (decide qué tool y argumentos, sin ejecutar nada) y
> `action_executor_node` (solo ejecuta si está aprobado). El plan estructurado (`action_plan`)
> viaja por el grafo con un `risk_level`; si es alto (como enviar un email), el edge condicional
> `route_from_planner` manda el flujo a `hitl_review` en vez de a `action_executor`. El
> `interrupt()` de LangGraph pausa ahí, y solo tras `Command(resume="approve")` se llega al
> executor. Es una versión previa de este sistema donde HITL se activaba por frases del LLM en
> la respuesta ("voy a enviar un email...") — lo cambié explícitamente porque eso significaba que
> el efecto de lado ya podía haber ocurrido antes de la 'aprobación', que era solo cosmética.

**P: ¿Cómo evitas ejecutar una acción dos veces si el humano aprueba por error dos veces, o hay
un retry de red?**
> El `action_plan` tiene `execution_status` y `executed_at`. El `hitl_node` rechaza cualquier
> nuevo intento de aprobación si la acción ya tiene `executed_at` seteado, y el
> `action_executor_node` chequea `execution_status == "succeeded"` antes de ejecutar y devuelve
> el resultado cacheado en vez de reejecutar. También hay un `idempotency_key` generado al
> planear, pensado para que la tool subyacente (si el proveedor real de email lo soporta) pueda
> deduplicar en su propio lado.

**P: ¿Qué pasa si la respuesta del humano no es exactamente "approve" o "reject"?**
> Se trata como rechazo automático por seguridad — no asumo aprobación implícita ante ninguna
> ambigüedad. Es un principio de fail-safe: el default ante lo inesperado es NO ejecutar la
> acción.

**P: ¿Por qué no meter TODAS las acciones en HITL, para máxima seguridad?**
> Porque mataría la productividad del sistema — cada ticket creado, cada consulta necesitaría
> esperar a un humano, y el punto de automatizar soporte interno se perdería. Por eso clasifico
> riesgo por tool: `enviar_email` es `high` (puede llegar a alguien fuera de la empresa, es
> difícil de revertir), `consultar_sql` es `medium` (lectura, pero de datos sensibles), crear/
> listar/buscar tickets es `low` (acción rutinaria, reversible, de bajo impacto). Solo el
> riesgo alto pausa para aprobación.

**P: ¿Cómo funciona técnicamente el `interrupt()` de LangGraph? ¿Qué pasa con el estado
mientras está pausado?**
> `interrupt()` lanza una excepción especial que LangGraph captura para pausar la ejecución del
> grafo en ese nodo exacto. El estado completo (`AgentState`) se persiste vía el checkpointer
> (`PostgresSaver` en producción si `DATABASE_URL` está set, `SqliteSaver` o `MemorySaver` en local)
> asociado a un `thread_id`. Cuando se llama de nuevo al grafo con `Command(resume=decision)` y el
> mismo `thread_id`, LangGraph recupera el estado guardado y continúa exactamente desde ese
> punto, como si nunca se hubiera detenido — el `interrupt()` original simplemente devuelve el
> valor pasado en `resume`.
