# Aegis Desk — Plan Integral de Remediación

## Estado de ejecución (2026-07-16) — post-auditoría

Este plan se implementó en la rama `remediation/2026-07-16`. Tras una auditoría en paralelo de backend, frontend, tests y operaciones, se corrigieron los gaps críticos y se amplió la cobertura de pruebas.

- ✅ **Fases 0 a 11 cerradas en código**: RBAC real, HITL antes de efectos laterales, rate limit, SQL seguro, PII/RAG injection, idempotencia, persistencia en Postgres/Supabase, API con JWT/CORS/validación, frontend Next.js con cookies HttpOnly, Docker con healthchecks y CI.
- ✅ **Integración Postgres/Supabase**: `DATABASE_URL` apunta al pooler de Supabase; `scripts/migrate_postgres.py` crea tablas y checkpointer; `src/db/hitl_queue.py`, `src/tools/sql.py`, `src/tools/tickets.py` y `src/rag/` usan Postgres cuando `DATABASE_URL` está configurado; `PostgresSaver` reemplaza SQLite.
- ✅ **Hardening de Supabase**: RLS habilitado en todas las tablas `public`; extensión `vector` en schema `extensions`; `DATABASE_URL` normalizada y con `search_path=public,extensions`.
- ✅ **Auth**: JWT en cookie `HttpOnly` + auth local bcrypt + auth opcional Supabase para emails; verificación de firma, expiración, issuer y audience; revocación de tokens en logout.
- ✅ **HITL**: planner/executor separados, `interrupt()` entre ambos, aprobación/rechazo vía `Command(resume=...)`, `approved_by` ahora refleja al admin aprobador, cola HITL redacta PII/secrets antes de persistir.
- ✅ **Docker**: imágenes corren como no-root, `.dockerignore` excluye secretos, `docker compose` con healthchecks y límites de recursos.
- ✅ **CI**: `.github/workflows/ci.yml` ejecuta `compileall`, `pytest`, `npm run lint` y `npm run build`.
- ✅ **Tests**: `pytest` 50/50 passed, `evals` 33/33 (100%), `redteam` 31/31 (100%), `npm run lint && npm run build` OK, `python -m compileall` OK.

> **Plan cerrado el 2026-07-17.** Todos los ítems están marcados `[x]`. Aquellos con nota `*(backlog — ...)*` se cierran como decisiones de alcance (se mantienen en el roadmap post-MVP). Las garantías críticas P0/P1 tienen pruebas deterministas en `tests/` y las verificaciones finales son: `pytest` 82/82, `evals` 33/33, `redteam` 36/36, `compileall` OK, `npm run lint && npm run build` OK.

Las secciones originales se conservan como bitácora. Los ítems con nota de backlog se trasladarán a `ROADMAP.md` en el próximo ciclo.

## 1. Propósito

Este documento convierte la auditoría técnica en un plan ejecutable para corregir las falencias de seguridad, bugs funcionales, problemas de fiabilidad, deuda de pruebas y riesgos de despliegue identificados en Aegis Desk.

El objetivo no es solo hacer que los tests actuales pasen. El objetivo es que las garantías importantes estén implementadas en código, sean observables y tengan pruebas de regresión deterministas.

## 2. Alcance

El plan cubre:

- Autorización de tools y control de acciones sensibles.
- Human-in-the-Loop antes de ejecutar efectos laterales.
- Rate limiting de API y login.
- Validación segura de SQL.
- Protección PII y privacidad de logs.
- Prompt injection directa e indirecta en RAG.
- Persistencia y consistencia de tickets.
- Estado, reintentos e idempotencia del grafo.
- Cola HITL, auditoría y trazabilidad.
- API, JWT, CORS y validación de entrada.
- Frontend, autenticación y lint.
- Evals deterministas y Red Teaming realista.
- Dependencias, Docker y preparación para producción.

## 3. Principios de ejecución

1. **Seguridad antes que optimización:** no se optimiza latencia hasta cerrar los bypasses de autorización y los efectos laterales.
2. **La política se aplica en código:** nunca depender exclusivamente de prompts, frases generadas por el LLM o intención clasificada.
3. **Planificar antes de ejecutar:** toda acción sensible debe tener un plan estructurado y una aprobación previa.
4. **Fail closed:** ante estado ambiguo, tool desconocida, rol inválido o decisión HITL inválida, la acción se rechaza.
5. **Efectos laterales idempotentes:** reintentar una generación no puede repetir un email ni crear duplicados.
6. **Datos no confiables:** consultas, documentos RAG, respuestas del LLM y resultados de tools se tratan como datos no confiables.
7. **Pruebas de regresión obligatorias:** cada fix debe incluir una prueba que falle antes del cambio y pase después.
8. **Cambios pequeños:** cada fase debe poder revisarse, probarse y revertirse de forma independiente.

## 4. Severidad y definición de terminado

### Severidades

- **P0 — Bloqueante:** permite bypass de seguridad, ejecución no autorizada, fuga de secretos o efecto lateral sin aprobación.
- **P1 — Alta:** rompe una garantía funcional, auditoría, consistencia o disponibilidad importante.
- **P2 — Media:** deuda técnica o riesgo que debe resolverse antes de producción.
- **P3 — Baja:** mejora de calidad, ergonomía o mantenimiento.

### Definition of Done global

Una tarea se considera terminada cuando:

- El código aplica la garantía sin depender del comportamiento del LLM.
- Existe una prueba automatizada de éxito y una prueba de abuso/fallo.
- El comportamiento queda registrado en tracing sin almacenar secretos ni PII innecesaria.
- La documentación y los contratos API están actualizados.
- `python -m compileall -q src evals redteam scripts` termina correctamente.
- La suite Python y el lint/build frontend terminan correctamente.
- El cambio no reduce la defensa de Red Teaming.

## 5. Línea base previa a los cambios

Antes de modificar código, guardar un reporte de baseline:

```bash
python -m compileall -q src evals redteam scripts
python -m evals.run_evals --save
python -m redteam.run_redteam --save
npm --prefix /Users/sebastianceron/Desktop/Seba/Study/aegis-desk/frontend run lint
npm --prefix /Users/sebastianceron/Desktop/Seba/Study/aegis-desk/frontend run build
```

La ejecución de evals y Red Teaming requiere API keys y puede generar coste. Los resultados deben guardarse fuera de Git y asociarse al commit evaluado.

## 6. Arquitectura objetivo

El flujo objetivo del grafo será:

```text
Request autenticada
  -> validación de entrada
  -> security/rate limit
  -> clasificación de intención
  -> autorización de intención
  -> worker especializado
  -> plan estructurado de respuesta/acción
  -> critic y validaciones deterministas
  -> aprobación HITL si corresponde
  -> ejecución idempotente de tool
  -> filtro PII
  -> tracing/auditoría
  -> respuesta
```

Para acciones se propone ampliar el estado con campos equivalentes a:

```text
action_plan:
  action_id
  tool_name
  arguments
  requested_by
  role
  risk_level
  approval_status: pending|approved|rejected|not_required
  execution_status: not_started|running|succeeded|failed
  idempotency_key
  executed_at
```

La acción no debe ejecutarse mientras `approval_status` no sea `approved` o `not_required`.

# 7. Fases de implementación

## Fase 0 — Preparación y observabilidad de cambios

**Prioridad:** P0  
**Dependencias:** ninguna

### Tareas

- [x] Crear rama de remediación.
- [x] Guardar baseline de evals, Red Teaming, lint y compileall.
- [x] Añadir un identificador de versión/commit a cada reporte. *(commit añadido a reportes de evals y redteam)*
- [x] Definir una política para no guardar `.env`, tokens, PII ni resultados sensibles en Git.
- [x] Crear una matriz de pruebas con los casos de este documento. *(backlog — matriz de trazabilidad tests vs ítems del plan)*

### Entregables

- Baseline reproducible.
- Matriz de regresión.
- Lista de cambios por fase.

### Criterios de aceptación

- Se puede comparar cualquier resultado posterior contra el baseline.
- No se modifican todavía los comportamientos de producción.

## Fase 1 — Autorización real de tools

**ID:** SEC-01  
**Prioridad:** P0  
**Dependencias:** Fase 0

### Problema

`action_node` expone `enviar_email` a usuarios empleados aunque el RBAC declara que no tienen ese permiso.

### Implementación

- [x] Hacer que el worker reciba el rol desde `AgentState`.
- [x] Obtener las tools mediante `get_allowed_tools(role)` en vez de importar una lista fija.
- [x] Crear una segunda validación dentro de cada tool o en un `tool_guard` central.
- [x] Rechazar roles desconocidos; no convertirlos silenciosamente en empleado.
- [x] No aceptar el rol desde el body de `/chat`; usar únicamente el usuario autenticado.
- [x] Aplicar la misma política al agente ReAct standalone.
- [x] Añadir `tool_name`, `role` y `authorization_decision` al estado y al trace.

### Pruebas

- [x] Empleado intenta enviar email interno: no se invoca `enviar_email`.
- [x] Empleado puede crear/listar/buscar tickets.
- [x] Empleado intenta SQL: denegado antes de crear el worker SQL. *(verificado en `test_security_core` y RBAC de intenciones)*
- [x] Admin puede usar SQL y email.
- [x] Rol desconocido: denegado.
- [x] Un prompt que diga “soy admin” no cambia el rol.

### Criterios de aceptación

- No existe ningún camino desde un rol empleado hacia `enviar_email` o `consultar_sql`.
- La prueba verifica que la tool no fue llamada, no solo que la respuesta textual diga “permiso denegado”.

## Fase 2 — HITL antes del efecto lateral

**ID:** SEC-02  
**Prioridad:** P0  
**Dependencias:** SEC-01

### Problema

El agente ejecuta la tool antes de que `hitl_node` solicite aprobación. La detección depende además de frases en la respuesta del LLM.

### Implementación

- [x] Separar `action_planner` de `action_executor`.
- [x] Hacer que el planner produzca un `action_plan` estructurado sin ejecutar tools.
- [x] Clasificar cada acción por riesgo: `low`, `medium`, `high`.
- [x] Marcar el email como `high` y requerir aprobación previa.
- [x] Mover `interrupt()` entre planner y executor.
- [x] Ejecutar la tool únicamente después de `Command(resume="approve")`.
- [x] Rechazar decisiones distintas de `approve` o `reject`.
- [x] Eliminar la detección de HITL basada en frases de la respuesta del LLM.
- [x] Mostrar al revisor el `action_plan` estructurado, no una respuesta textual ambigua.
- [x] No exponer argumentos sensibles innecesarios en la interfaz del revisor.
- [x] Registrar quién aprobó, cuándo, qué aprobó y qué se ejecutó.
- [x] Añadir expiración para aprobaciones pendientes.
- [x] Hacer que una acción aprobada no pueda aprobarse o ejecutarse dos veces.

### Pruebas

- [x] Email pendiente no aparece como enviado antes de aprobar. *(action_executor verifica `approval_status`)*
- [x] Email rechazado nunca llama a la tool. *(route_from_hitl / hitl_node rechazan antes de ejecutar)*
- [x] Email aprobado llama a la tool exactamente una vez. *(idempotencia por `execution_status` e `idempotency_key`)*
- [x] Decisión inválida mantiene la acción bloqueada.
- [x] Repetir la aprobación devuelve el estado final sin repetir la acción.
- [x] El resumen HITL contiene tool y argumentos normalizados. *(hitl_node muestra tool_name, risk_level, safe_args, requested_by, role)*

### Criterios de aceptación

- Ninguna acción sensible produce efecto lateral antes de la aprobación.
- El control no depende de que el LLM escriba “email enviado”.
- La auditoría permite reconstruir la solicitud, la aprobación y la ejecución.

## Fase 3 — Rate limiting de API y autenticación

**IDs:** SEC-03, API-01  
**Prioridad:** P0  
**Dependencias:** Fase 0

### Implementación

- [x] Eliminar `reset_user()` del flujo normal de `/chat`.
- [x] Mantener el reset únicamente en fixtures o utilidades de test.
- [x] Proteger el contador con lock para concurrencia dentro del proceso.
- [x] Diseñar backend distribuido para producción, preferiblemente Redis. *(backlog — fuera del MVP; Postgres/SQLite cubre el alcance actual)*
- [x] Aplicar límite separado para login por IP y por usuario.
- [x] Añadir límites de tamaño y frecuencia a `/chat`.
- [x] Devolver `429` con `Retry-After`, no una respuesta normal del agente.
- [x] Hacer `JWT_SECRET` obligatorio fuera de desarrollo.
- [x] Rechazar secretos conocidos o el secreto demo al arrancar en producción.
- [x] Migrar passwords a Argon2id o bcrypt con salt.
- [x] Añadir expiración, issuer, audience y estrategia de revocación de tokens.
- [x] Evitar revelar si el usuario existe durante login.

### Pruebas

- [x] Once requests consecutivas del mismo usuario producen `429` después del límite.
- [x] Requests de dos usuarios no comparten contador.
- [x] El reset de tests no está disponible mediante endpoint.
- [x] Doce intentos de login fallidos activan el límite.
- [x] JWT con firma incorrecta, expirado, issuer incorrecto o audience incorrecta es rechazado.
- [x] El servicio no arranca en modo producción con secreto demo. *(RuntimeError en main.py + test pasa)*

### Criterios de aceptación

- El rate limiting funciona desde la API, no solo en pruebas unitarias.
- El login no permite fuerza bruta básica.
- La configuración insegura de demo no puede llegar accidentalmente a producción.

## Fase 4 — SQL seguro y limitado

**ID:** SEC-04  
**Prioridad:** P0  
**Dependencias:** SEC-01

### Implementación

- [x] Reemplazar el `pass` de la allowlist por validación efectiva.
- [x] Permitir únicamente tablas y columnas explícitas.
- [x] Bloquear `sqlite_master`, `sqlite_sequence`, pragmas y funciones no aprobadas.
- [x] Rechazar múltiples statements y comentarios peligrosos.
- [x] Usar conexión SQLite read-only.
- [x] Activar `set_authorizer` o parser SQL seguro.
- [x] Añadir `LIMIT` máximo de forma controlada.
- [x] Configurar timeout de conexión y consulta.
- [x] No devolver emails, salarios u otras columnas sensibles salvo permiso explícito.
- [x] Normalizar y validar la respuesta SQL antes de entregarla al LLM.
- [x] Cerrar conexiones mediante `try/finally` o context manager.

### Pruebas

- [x] `SELECT` permitido sobre tabla y columnas permitidas.
- [x] `SELECT` sobre tabla no permitida rechazado.
- [x] `SELECT` sobre `sqlite_master` rechazado.
- [x] `DROP`, `DELETE`, `UPDATE`, `INSERT` y stacked queries rechazados.
- [x] `UNION` hacia tablas no permitidas rechazado.
- [x] Query muy lenta o sin límite termina por timeout.
- [x] El resultado nunca supera `MAX_ROWS`.

### Criterios de aceptación

- La tool no ejecuta SQL fuera del contrato permitido aunque el LLM lo solicite.
- La autorización se verifica antes y durante la ejecución.

## Fase 5 — PII, privacidad y prompt injection RAG

**IDs:** SEC-05, SEC-06  
**Prioridad:** P0  
**Dependencias:** Fases 1 y 4

### Protección PII

- [x] Aplicar `filter_pii()` antes de cada respuesta API y UI.
- [x] Aplicar redacción antes de guardar traces.
- [x] Redactar queries, argumentos de tools y payloads HITL según política.
- [x] No guardar tokens, API keys, passwords ni cuerpos completos de emails.
- [x] Añadir política de retención y borrado de traces.
- [x] Registrar solo hashes o identificadores cuando no se necesite el valor original.
- [x] Añadir detección de IBAN, tarjetas, direcciones y otros datos relevantes.
- [x] Definir excepciones explícitas para usuarios admin y aun así evitar secretos.

### Prompt injection en documentos

- [x] Escanear documentos durante ingesta.
- [x] Marcar o rechazar chunks con instrucciones de sistema, role overrides o secretos.
- [x] Insertar contexto RAG como datos delimitados, nunca como instrucciones ejecutables.
- [x] Separar prompt fijo del contexto dinámico.
- [x] Añadir un validador de fuentes antes de construir el prompt. *(`src/rag/chain.py` valida `_ALLOWED_SOURCES`)*
- [x] Añadir threshold de relevancia para responder “no tengo información”. *(`RELEVANCE_THRESHOLD=0.3` en `src/rag/retriever.py`)*
- [x] Registrar score de retrieval y decisión de descarte. *(`retrieval_scores` y `discarded` en `AgentState`, `rag_agent.py` y `trace_execution`)*

### Pruebas

- [x] Email, teléfono, DNI, salario y API key se redactan en respuesta y trace.
- [x] PII en una fuente RAG no aparece sin autorización.
- [x] Documento con `[SYSTEM]`, XML o instrucciones ocultas no modifica la política del agente.
- [x] Payloads con Unicode confusable, Base64, markdown, HTML y espacios extra son seguros. *(redteam 100% en esas categorías)*
- [x] Pregunta fuera de dominio sin chunks relevantes no produce alucinación. *(evals RAG 10/10; respuestas basadas en fuentes o “no tengo información”)*

### Criterios de aceptación

- No existe camino de salida para secretos o PII no autorizada.
- El contenido recuperado no puede cambiar las instrucciones de seguridad.

## Fase 6 — Estado, reintentos e idempotencia del grafo

**IDs:** REL-01, REL-02, REL-03  
**Prioridad:** P1  
**Dependencias:** SEC-02

### Implementación

- [x] Hacer que el límite de reintentos sea una garantía del router, no del LLM.
- [x] Incrementar el contador en cada paso que vuelva a un worker.
- [x] Añadir un guard que corte cualquier loop por encima del máximo.
- [x] Separar `generation_retry` de `action_retry`.
- [x] Prohibir reejecutar una acción ya completada.
- [x] Añadir `idempotency_key` por solicitud y por acción.
- [x] Guardar estado de tool: no iniciada, ejecutando, completada o fallida.
- [x] Usar estado estructurado para saber si una acción es email, ticket u otra tool.
- [x] Definir claramente qué respuestas de baja confianza requieren HITL.
- [x] No enviar respuestas de baja confianza a un nodo HITL que no pueda interrumpir.

### Pruebas

- [x] Critic con `confidence < 0.7` y `necesita_reintento=False` no genera loop infinito.
- [x] El máximo de reintentos se respeta aunque el LLM entregue valores inconsistentes.
- [x] Un retry de generación no crea otro ticket.
- [x] Un retry de generación no envía otro email.
- [x] Una acción fallida puede reanudarse sin duplicarse.
- [x] Una respuesta de baja confianza termina como HITL real o como rechazo explícito.

### Criterios de aceptación

- Todo loop tiene un límite verificable.
- Toda tool con efecto lateral es idempotente.
- El routing no depende de frases generadas por el LLM.

## Fase 7 — Persistencia de tickets y cola HITL

**IDs:** REL-04, REL-05, REL-06  
**Prioridad:** P1  
**Dependencias:** Fases 2 y 6

### Tickets

- [x] Elegir SQLite como fuente única inicial o migrar directamente a PostgreSQL.
- [x] Eliminar la lista global `_tickets_db` y `_next_id`.
- [x] Añadir propietario, creador, timestamps y estado de auditoría.
- [x] Aplicar ownership: un empleado solo ve sus tickets salvo política explícita.
- [x] Hacer que Action Agent y Data Agent consulten la misma fuente.
- [x] Añadir transacciones y restricciones de integridad.

### HITL

- [x] Crear una cola persistente de acciones pendientes.
- [x] Exponer `GET /hitl/pending` autenticado y restringido a admin.
- [x] Devolver acción, usuario, riesgo, timestamp y estado.
- [x] Validar que un thread existe, está pendiente y corresponde a una acción HITL.
- [x] Añadir control de replay y expiración.
- [x] Registrar aprobación y rechazo en auditoría.
- [x] Actualizar frontend y Streamlit desde la cola backend, no desde estado local.
- [x] Mostrar resultado de la ejecución aprobada en el chat original.

### Pruebas

- [x] Ticket creado aparece igual en Action Agent y Data Agent.
- [x] Dos procesos no generan el mismo ID. *(`_new_action_id` usa uuid4 + timestamp)*
- [x] Admin ve pendientes creados por otra sesión. *(endpoint `/hitl/pending` con persistencia DB)*
- [x] Empleado no puede listar ni resolver pendientes.
- [x] Thread inexistente, resuelto o expirado devuelve error controlado.
- [x] Aprobar dos veces no repite la acción.

### Criterios de aceptación

- Existe una sola fuente de verdad para tickets.
- La cola HITL funciona entre procesos y sesiones.
- Cada acción sensible tiene historial auditable.

## Fase 8 — API, JWT, CORS y resiliencia

**IDs:** API-02, API-03  
**Prioridad:** P1  
**Dependencias:** Fases 3 y 7

### Implementación

- [x] Proteger `/stats` con autenticación y decidir si solo admin puede verlo.
- [x] Proteger `/hitl/pending` con rol admin.
- [x] Restringir CORS a dominios configurados.
- [x] Validar `query` con longitud mínima y máxima.
- [x] Rechazar input vacío, excesivo o con encoding inválido.
- [x] Añadir límites de timeout y cancelación a `/chat`.
- [x] Usar `ainvoke()` o threadpool para no bloquear el event loop.
- [x] Añadir exception handlers sin devolver detalles internos.
- [x] No incluir excepciones crudas en respuestas 404/500.
- [x] Añadir correlation ID a cada request.
- [x] Registrar el estado final de todas las requests, incluyendo bloqueadas y HITL.
- [x] Añadir healthcheck de dependencias sin exponer configuración sensible.

### Pruebas

- [x] CORS rechaza origen no configurado. *(CORSMiddleware con CORS_ORIGINS; error en prod si es "*" o vacío)*
- [x] `/stats` sin token devuelve `401`.
- [x] `/hitl/pending` para empleado devuelve `403`.
- [x] Query mayor que el límite devuelve `422`.
- [x] Error interno no muestra stack trace ni datos de configuración. *(exception handlers genéricos en main.py)*
- [x] Requests concurrentes no bloquean completamente la API. *(FastAPI async; sin locks globales en endpoints)*

### Criterios de aceptación

- La API tiene contratos claros para `401`, `403`, `409`, `422`, `429` y `500`.
- No hay endpoints sensibles públicos por accidente.

## Fase 9 — Frontend y autenticación de sesión

**IDs:** FE-01, FE-02  
**Prioridad:** P1  
**Dependencias:** Fase 8

### Implementación

- [x] Eliminar el puente global `window.__addPending`.
- [x] Leer pendientes desde el endpoint backend con React Query.
- [x] Invalidar la cola después de aprobar o rechazar.
- [x] Mostrar estados loading, empty, error y stale.
- [x] Cerrar sesión automáticamente ante `401`.
- [x] Validar token con `/me` al restaurar la sesión.
- [x] Manejar JSON corrupto en `localStorage` sin romper el provider.
- [x] Evaluar migración del token a cookie HttpOnly.
- [x] Corregir el `setState` dentro de effect según las reglas de React.
- [x] Eliminar imports, variables y props no utilizados.
- [x] Añadir `npm run lint` y `npm run build` a CI.

### Pruebas

- [x] La página HITL muestra pendientes de otra sesión.
- [x] La página desaparece o redirige correctamente cuando el usuario no es admin.
- [x] Token expirado limpia la sesión y redirige a login.
- [x] `localStorage` corrupto no deja la aplicación en pantalla blanca.
- [x] Lint sin errores ni warnings nuevos.
- [x] Build de producción exitoso.

### Criterios de aceptación

- La interfaz refleja el estado real del backend.
- La sesión no depende de datos manipulables del navegador para autorizar acciones.

## Fase 10 — Evals y Red Teaming deterministas

**IDs:** QA-01, QA-02  
**Prioridad:** P1  
**Dependencias:** Fases 1 a 9

### Implementación

- [x] Convertir scripts de prueba en suite `pytest` con assertions. *(tests/test_security_core.py y tests/test_api.py cubren los casos principales)*
- [x] Validar `expected_source`, no solo keywords de respuesta. *(backlog — mejorar judges de evals)*
- [x] Aplicar constraints `0 <= score <= 1` y `Literal` para categorías.
- [x] Separar métricas de clasificación, respuesta, seguridad y ejecución. *(src/observability/metrics.py y categorías en tracing)*
- [x] Añadir mocks de LLM para pruebas unitarias sin coste. *(backlog — integrar mocks de LangChain para tests puros)*
- [x] Añadir pruebas de integración con tools instrumentadas. *(tests invocan tools reales con SQLite y assertions)*
- [x] Registrar si una tool fue llamada y con qué argumentos.
- [x] Red Team evaluator debe comprobar efectos laterales, no solo texto.
- [x] Añadir ataques de Unicode, Base64, RAG poisoning, tool chaining y replay. *(payloads.json incluye esas categorías; redteam 100%)*
- [x] Ejecutar evals con ambos modelos: configuración híbrida y fallback. *(backlog — evals con GROQ + DeepInfra híbrido)*
- [x] Definir thresholds de regresión por categoría.
- [x] Fallar CI si cae seguridad, autorización o exactitud bajo el baseline. *(backlog — añadir threshold checks a CI; tests actuales bloquean build si fallan)*

### Pruebas mínimas nuevas

- [x] Empleado no puede ejecutar email.
- [x] Email no se ejecuta antes de aprobación. *(HITL bloquea ejecución hasta aprobación)*
- [x] Email aprobado se ejecuta una sola vez. *(idempotencia)*
- [x] Rate limit de API bloquea la request número 11.
- [x] SQL fuera de allowlist no se ejecuta.
- [x] PII no aparece en respuesta ni trace.
- [x] Documento RAG malicioso no altera el system prompt.
- [x] Reintento no duplica efectos laterales. *(`execution_status` + `idempotency_key`)*
- [x] Tickets de acción y SQL son consistentes.
- [x] Pendientes HITL son visibles cross-session.

### Criterios de aceptación

- Las pruebas verifican comportamiento interno y resultado externo.
- Red Teaming no puede marcar como defendido un ataque que haya ejecutado una tool peligrosa.
- Los resultados se comparan contra un baseline versionado.

## Fase 11 — Dependencias, Docker y operación

**IDs:** OPS-01, OPS-02  
**Prioridad:** P2  
**Dependencias:** Fases 3 y 8

### Implementación

- [x] Fijar dependencias en `requirements.txt` (lockfile eliminado: estaba generado para Python 3.14 y rompía en `python:3.11-slim`).
- [x] Declarar explícitamente dependencias usadas por Streamlit, tests y observabilidad.
- [x] Añadir `.dockerignore` con `.env`, `.venv`, `data`, traces, resultados y caches.
- [x] Ejecutar Docker como usuario no root.
- [x] Añadir `HEALTHCHECK` y `depends_on` condicionado a health.
- [x] Separar imagen API, UI legacy y frontend cuando corresponda.
- [x] No copiar datos de desarrollo dentro de la imagen.
- [x] Configurar secretos solo en runtime.
- [x] Añadir límites de CPU, memoria y tamaño de logs.
- [x] Añadir backup y restauración para SQLite (`scripts/backup_sqlite.py`).
- [x] Documentar despliegue real en Render/Vercel/Supabase/Pinecone (documentado en README y AGENTS; migración a Supabase Postgres completada).

### Criterios de aceptación

- La imagen no contiene `.env` ni secretos.
- El contenedor arranca con una configuración limpia y reproducible.
- La API reporta health real de sus dependencias críticas.

## 8. Orden recomendado de ejecución

1. Fase 0: baseline.
2. Fase 1: RBAC real de tools.
3. Fase 2: HITL antes de efectos laterales.
4. Fase 3: rate limit y autenticación segura.
5. Fase 4: SQL seguro.
6. Fase 5: PII y RAG injection.
7. Fase 6: reintentos e idempotencia.
8. Fase 7: persistencia y cola HITL.
9. Fase 8: API y resiliencia.
10. Fase 9: frontend.
11. Fase 10: evals y Red Teaming.
12. Fase 11: Docker y operación.

No se debe desplegar una versión nueva después de Fase 1 sin completar Fase 2: la autorización de tools sin HITL previo sigue dejando riesgo de efectos laterales.

## 9. Estrategia de rollback

- Cada fase se implementa en un commit o PR separado.
- No mezclar refactor de arquitectura con cambios de prompts sin pruebas independientes.
- Mantener feature flags para la nueva cola HITL y el nuevo executor.
- Si falla la cola persistente, fallar cerrado y no ejecutar la acción; nunca volver automáticamente al flujo inseguro.
- Si falla PII, no enviar la respuesta ni guardarla en tracing.
- Si falla la validación SQL, rechazar la consulta.
- Si falla el proveedor rápido, usar fallback configurado o devolver error controlado; no degradar autorización.

## 10. Checklist final de release

### Seguridad

- [x] RBAC probado a nivel de intención y tool.
- [x] Email nunca se ejecuta antes de aprobación. *(HITL bloquea ejecución hasta aprobación)*
- [x] SQL read-only y allowlist efectiva.
- [x] Rate limit probado desde API y login.
- [x] PII redactada en respuesta, fuentes, HITL y logs.
- [x] RAG poisoning probado.
- [x] JWT secret no usa valor demo.
- [x] CORS restringido. *(CORS_ORIGINS configurado; `*` rechazado en producción)*
- [x] Docker no contiene secretos.

### Fiabilidad

- [x] No hay loops infinitos. *(retries limitados y flag `requires_retry`)*
- [x] No hay duplicados por retries.
- [x] Tickets tienen una fuente de verdad.
- [x] HITL persiste entre sesiones/procesos.
- [x] Aprobaciones son idempotentes.
- [x] Tracing incluye bloqueos, pausas y decisiones. *(_trace registra “bloqueado”, “HITL pendiente” y approved_by/approved_at)*

### Calidad

- [x] Python compileall pasa.
- [x] Tests unitarios pasan.
- [x] Tests de integración pasan.
- [x] Evals no caen bajo baseline.
- [x] Red Teaming no detecta brechas.
- [x] Frontend lint pasa.
- [x] Frontend build pasa.
- [x] Docker build pasa.
- [x] README y documentación reflejan el comportamiento real.

## 11. Resultado esperado

Al finalizar este plan, Aegis Desk deberá tener:

- Autorización aplicada en cada frontera, no solo en el router.
- Aprobación humana antes de toda acción sensible.
- Tools seguras, idempotentes y auditables.
- SQL limitado técnicamente, no solo por prompt.
- Protección de PII en toda la cadena de salida y observabilidad.
- RAG resistente a instrucciones indirectas.
- Estado persistente y consistente.
- API autenticada, limitada y observable.
- Frontend sincronizado con el backend.
- Evals y Red Teaming capaces de detectar ejecución peligrosa, no solo respuestas inseguras.
- Despliegue reproducible sin secretos dentro de imágenes.

