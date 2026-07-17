# 5. Seguridad en sistemas de IA (RBAC, prompt injection, PII, rate limiting, SQL)

## Concepto: por qué la seguridad en LLM apps es distinta

Un LLM no es un componente de software determinista: no puedes "probar formalmente" que nunca va
a decir algo indebido solo con el prompt. Por eso el principio central es
**defense-in-depth**: no confiar en una sola capa (y mucho menos en "el LLM se va a negar"), sino
apilar varias capas independientes donde cada una asume que la anterior puede fallar.

Vectores de ataque específicos de LLM apps:
- **Prompt injection directa**: el usuario intenta hacer que el modelo ignore sus instrucciones
  del sistema ("ignora tus reglas", "ahora eres admin").
- **Prompt injection indirecta / RAG poisoning**: la inyección viene de datos que el sistema
  "confía" (un documento indexado, resultado de una tool, un email) en vez del input directo del
  usuario.
- **Jailbreaks**: técnicas más elaboradas (roleplay, "modo desarrollador", traducción como
  vector, etc.) para lograr el mismo objetivo que la injection directa.
- **RBAC bypass**: intentar que el agente ejecute una acción o entregue datos fuera del rol del
  usuario (ej. un empleado pidiendo salarios de otros).
- **Tool abuse**: manipular argumentos de una tool para que haga algo distinto de lo previsto.
- **SQL injection**: si un agente construye/ejecuta SQL, el mismo riesgo clásico aplica, agravado
  porque quien "escribe" el SQL a veces es el propio LLM a partir de lenguaje natural.
- **Data exfiltration / PII leakage**: el modelo repite en texto plano datos sensibles que tenía
  en el contexto (de una tool, de RAG, de la DB).

## Cómo está implementado en Aegis Desk — las 4 capas

Ver <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/security/AGENTS.md" />
y el diagrama del README:

```
Capa 1: Security Node     → bloquea prompt injection + rate limit (regex, determinista)
Capa 2: RBAC              → deniega acceso por rol (empleado vs admin), en código
Capa 3: LLM refusal       → el modelo se niega a cooperar con ataques (menos confiable, es la última línea "suave")
Capa 4: HITL              → humano aprueba antes de ejecutar acciones sensibles
```

La idea clave para la entrevista: **las capas 1, 2 y 4 son deterministas (código), no dependen
del LLM**. Solo la capa 3 depende del comportamiento del modelo, y por diseño está en el medio,
no es la única defensa.

### Capa 1 — Prompt injection + rate limiting

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/security/prompt_injection.py" />:
- `detect_prompt_injection(text)`: lista de regex compiladas que buscan patrones típicos
  (`ignora las instrucciones`, `you are now admin`, `reveal your system prompt`, `DAN mode`,
  `[SYSTEM]`, `<system>`, etc.), case-insensitive, en español e inglés.
- `sanitize_input(text)`: neutraliza tags tipo `[SYSTEM]`/`<system>` reemplazándolos con texto
  inofensivo — se usa tanto en el `security_node` (input del usuario) como en `ingest.py`
  (contenido de documentos antes de indexar → protección contra RAG poisoning).
- Es **regex determinista**, no un LLM clasificando — más rápido, sin costo, y sobre todo
  **auditable y testeable con unit tests exactos** (no depende de que un modelo "opine" igual
  cada vez).

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/security/rate_limiter.py" />:
- Ventana deslizante en memoria: `MAX_REQUESTS = 10` cada `WINDOW_SECONDS = 120`. Limpia
  timestamps viejos en cada check (`cutoff = now - WINDOW_SECONDS`), cuenta los que quedan, y
  decide. Limitación conocida: es un diccionario en memoria del proceso — no persiste entre
  reinicios y no funciona out-of-the-box multi-instancia (necesitaría Redis o similar en un
  despliegue con varios workers).

### Capa 2 — RBAC

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/security/rbac.py" />:
- `ROLE_PERMISSIONS`: mapea rol → lista de nombres de tools permitidas (`empleado` no tiene
  `enviar_email` ni `consultar_sql`; `admin` sí).
- `ROLE_INTENTIONS`: mapea rol → intenciones/workers permitidos (`empleado` no puede ir a
  `datos`).
- `validate_role(role)` + **fail-closed**: si el rol no está en `VALID_ROLES`, las funciones
  lanzan `ValueError` en vez de devolver una lista vacía silenciosamente. Esto es importante:
  **fail-closed** (denegar por defecto ante ambigüedad) es el principio de seguridad correcto,
  vs fail-open (permitir por defecto), que es un anti-patrón común.
- `get_allowed_tools(role)`: el `action_agent` y `react_agent` piden literalmente la lista de
  tools permitidas ANTES de construir el prompt del planner — el LLM ni siquiera **ve** las
  tools prohibidas en su lista de opciones. Esto es más robusto que "dar todas las tools y
  confiar en que el LLM no use la prohibida".
- El grafo aplica RBAC en el edge `route_from_supervisor` **antes** de llegar al worker
  (<ref_snippet file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/agents/graph.py" lines="41-66" />):
  si `can_access(role, intencion)` es `False`, redirige a `chat_agent` con un mensaje de acceso
  denegado, sin ejecutar el worker real.
- El `action_planner_node` y `action_executor_node` **revalidan** RBAC dos veces (al planear y al
  ejecutar) — defensa en profundidad dentro del mismo dominio, no solo confiar en el check del
  router.

### Capa 3 — Comportamiento del LLM ("refusal")

El `chat_agent` tiene lógica anti-injection en el prompt (última línea de defensa "suave") y los
system prompts de cada worker son explícitos sobre no seguir instrucciones que vengan de
contenido de usuario/documentos. Esto se prueba empíricamente en el red team (archivo 8), no se
puede "demostrar" que siempre funcione — de ahí la necesidad de las otras capas.

### Capa 4 — HITL

Ver archivo 6 en detalle. Acciones de `risk_level == "high"` (enviar email) pausan el grafo para
aprobación humana antes de ejecutarse.

### PII masking

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/security/pii_filter.py" />:
- Regex para emails, teléfonos (formato español), DNI, y pares clave-valor sensibles
  (`salario: 75000` → `salario: ***`).
- `filter_pii()` se aplica a: la respuesta final de la API (`main.py`), la respuesta de RAG
  (`chain.py`), y antes de guardar en tracing — el principio es **no persistir ni devolver PII
  en texto plano en ningún punto de salida**, no solo "esconderla en el front".
- Enmascarado parcial y reversible-por-contexto (`a***@aegiscorp.com` en vez de `***`
  completo) — mantiene utilidad de la respuesta sin exponer el dato completo.

### SQL — defensa en profundidad específica

<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/tools/sql.py" /> es el
ejemplo más denso de defense-in-depth del proyecto, con **5 capas dentro de una sola tool**:
1. Backend dual: si `DATABASE_URL` está configurado, la query corre contra **Postgres/Supabase**
   en modo solo lectura (`read_only=True` + `default_transaction_read_only=on`). Si no, conexión
   SQLite en modo **solo lectura** a nivel de archivo (aunque el código tuviera un bug, el sistema
   operativo/DB no permite escribir).
2. `sqlite3.set_authorizer(_authorizer)` (SQLite) o sesión read-only (Postgres): autoriza/deniega
   cada operación a nivel de motor de base de datos — deniega `INSERT/UPDATE/DELETE/DROP/PRAGMA/
   ATTACH/...` explícitamente, y solo permite `SQLITE_READ` sobre tablas en `ALLOWED_TABLES`
   (allowlist, no blocklist). En Postgres se delega al modo read-only de la sesión.
3. Validación de la query como string ANTES de ejecutarla: debe empezar con `SELECT`, no puede
   tener `;` (bloquea *stacked queries*), y se le quitan comentarios (`--`, `/* */`) antes de
   validar (para que un atacante no pueda esconder un segundo statement en un comentario).
4. `MAX_ROWS = 50` y `QUERY_TIMEOUT` — limita el "blast radius" de una consulta legítima pero
   costosa o mal formada.
5. Enmascarado de columnas sensibles (`email`, `salario`) en el output, incluso si la query en sí
   era válida y autorizada — la última capa asume que todo lo anterior podría fallar.

Esto es notable porque el SQL en este sistema **lo genera un LLM** (el `action_planner`/
`react_agent` decide qué SQL correr a partir de lenguaje natural) — no puedes confiar en que el
LLM nunca genere algo peligroso, así que la defensa tiene que estar en el motor de datos, no en
"pedirle amablemente al LLM que solo haga SELECT".

**Nota de producción:** Cuando `DATABASE_URL` está set, los datos (`empleados`, `departamentos`,
`tickets`) viven en **Supabase PostgreSQL** con RLS habilitado en todas las tablas `public`.
El fallback sigue siendo SQLite local.

## Preguntas de entrevista

**P: ¿Cómo defiendes tu sistema contra prompt injection?**
> Con defense-in-depth: (1) detección regex determinista de patrones de injection en el input
> del usuario, antes de que llegue a cualquier LLM; (2) sanitización de contenido indexado en
> RAG para prevenir poisoning indirecto; (3) RBAC en código que ni siquiera expone tools
> prohibidas al LLM, así que aunque la injection "convenza" al modelo, no tiene la tool
> disponible para ejecutar algo fuera de su rol; (4) HITL para acciones de alto riesgo como
> emails. No dependo de que el LLM "se niegue" como única defensa — eso lo pruebo con red
> teaming, pero no confío en ello solo.

**P: ¿Por qué RBAC en código y no solo en el prompt del sistema ("no le muestres SQL a
empleados")?**
> Porque un prompt es una sugerencia probabilística, no una garantía. Filtro las tools
> disponibles ANTES de construir el prompt del LLM (`get_allowed_tools(role)`), así que un
> empleado literalmente no tiene la tool `consultar_sql` en su lista de opciones — no es que el
> LLM "decida no usarla", es que no existe para él. Además el executor revalida el permiso otra
> vez antes de ejecutar, por si el plan viene de un flujo que se manipuló.

**P: ¿Cómo te asegura tu tool de SQL que un LLM no pueda hacer algo destructivo?**
> Si `DATABASE_URL` está set, la query corre contra Postgres/Supabase en modo solo lectura
> (`default_transaction_read_only=on`) con la misma validación textual. El fallback es SQLite con
> `set_authorizer`, que es un callback del motor de base de datos que autoriza/deniega cada
> operación a nivel de fila/tabla/función — no una validación de string que un atacante podría
> eludir con ofuscación. En ambos casos: conexión de solo lectura, allowlist de tablas, validación
> de que el string sea un SELECT sin múltiples statements, límites de filas/tiempo, y enmascaro
> columnas sensibles en el resultado. Es defense-in-depth dentro de una sola tool, porque el SQL
> lo genera un LLM a partir de lenguaje natural y no puedo asumir que siempre generará
> exactamente lo que espero.

**P: ¿Qué es "fail-closed" y dónde lo aplicas?**
> Es negar acceso por defecto cuando hay ambigüedad, en vez de permitir por defecto. Lo aplico en
> `rbac.py`: si un rol no está en `VALID_ROLES`, las funciones lanzan `ValueError` en vez de
> devolver una lista vacía de tools silenciosamente (lo cual podría interpretarse en otro punto
> del código como "sin restricciones"). El router del grafo captura ese error y redirige a
> chat_agent con acceso denegado.

**P: ¿Cómo evitas que el sistema filtre PII en sus respuestas?**
> Con un filtro de PII basado en regex (`filter_pii`) que se aplica en cada punto de salida:
> respuesta de la API, respuesta de RAG, y antes de persistir en tracing — no solo en un punto,
> porque cualquiera de esos flujos podría exponer datos si el filtro solo estuviera en uno.
> Enmascara emails, teléfonos, DNIs, y pares clave-valor tipo "salario: X".

**P: ¿Qué limitaciones conoces de tu propio sistema de seguridad?**
> El rate limiter sigue siendo en memoria y por proceso — no escala multi-instancia sin Redis.
> La detección de prompt injection es regex, no un clasificador de ML, así que tiene falsos
> negativos ante ataques más sofisticados (lo mido con red teaming, no lo asumo). El JWT/auth usa
> configuración simple para el propósito de aprendizaje del proyecto — en producción real reforzaría
> rotación de secretos y expiraciones más estrictas. La persistencia de cola HITL y datos ya
> puede correr en Supabase/Postgres cuando `DATABASE_URL` está set.
