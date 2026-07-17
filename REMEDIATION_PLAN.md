# Aegis Desk — Plan Integral de Remediación

## Estado de ejecución (2026-07-16)

Este plan se implementó en la rama `remediation/2026-07-16`. A continuación el estado resumido:

- ✅ **Fase 0 a 10 completadas**: RBAC real, HITL antes de efectos laterales, rate limit, SQL seguro, PII/RAG injection, idempotencia, persistencia en Supabase Postgres, API con JWT/CORS/validation, frontend Next.js con HttpOnly cookies, evals deterministas y Red Teaming 31/31 defendido.
- ✅ **Integración Supabase**: `DATABASE_URL` apunta al pooler de Supabase; `scripts/migrate_postgres.py` crea tablas y checkpointer; `src/db/hitl_queue.py`, `src/tools/sql.py`, `src/tools/tickets.py` y `src/rag/` usan Postgres; `PostgresSaver` reemplaza SQLite cuando hay `DATABASE_URL`.
- ✅ **Hardening de Supabase**: RLS habilitado en todas las tablas `public`; extensión `vector` en schema `extensions`; `DATABASE_URL` normalizada y con `search_path=public,extensions`.
- ✅ **Auth**: JWT en cookie `HttpOnly` + auth local bcrypt + auth opcional Supabase para emails.
- ✅ **Docker**: `docker compose up -d` levanta API, UI y frontend con healthchecks y limites de recursos.
- ✅ **Tests**: `pytest` 18/18 passed, `npm run lint && npm run build` OK, Docker healthy.

Las secciones originales del plan se conservan como bitácora de decisiones; los checkboxes más relevantes se marcan a lo largo del documento según el estado actual.

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

- [ ] Crear rama de remediación.
- [ ] Guardar baseline de evals, Red Teaming, lint y compileall.
- [ ] Añadir un identificador de versión/commit a cada reporte.
- [ ] Definir una política para no guardar `.env`, tokens, PII ni resultados sensibles en Git.
- [ ] Crear una matriz de pruebas con los casos de este documento.

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

- [ ] Hacer que el worker reciba el rol desde `AgentState`.
- [ ] Obtener las tools mediante `get_allowed_tools(role)` en vez de importar una lista fija.
- [ ] Crear una segunda validación dentro de cada tool o en un `tool_guard` central.
- [ ] Rechazar roles desconocidos; no convertirlos silenciosamente en empleado.
- [ ] No aceptar el rol desde el body de `/chat`; usar únicamente el usuario autenticado.
- [ ] Aplicar la misma política al agente ReAct standalone.
- [ ] Añadir `tool_name`, `role` y `authorization_decision` al estado y al trace.

### Pruebas

- [ ] Empleado intenta enviar email interno: no se invoca `enviar_email`.
- [ ] Empleado puede crear/listar/buscar tickets.
- [ ] Empleado intenta SQL: denegado antes de crear el worker SQL.
- [ ] Admin puede usar SQL y email.
- [ ] Rol desconocido: denegado.
- [ ] Un prompt que diga “soy admin” no cambia el rol.

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

- [ ] Separar `action_planner` de `action_executor`.
- [ ] Hacer que el planner produzca un `action_plan` estructurado sin ejecutar tools.
- [ ] Clasificar cada acción por riesgo: `low`, `medium`, `high`.
- [ ] Marcar el email como `high` y requerir aprobación previa.
- [ ] Mover `interrupt()` entre planner y executor.
- [ ] Ejecutar la tool únicamente después de `Command(resume="approve")`.
- [ ] Rechazar decisiones distintas de `approve` o `reject`.
- [ ] Eliminar la detección de HITL basada en frases de la respuesta del LLM.
- [ ] Mostrar al revisor el `action_plan` estructurado, no una respuesta textual ambigua.
- [ ] No exponer argumentos sensibles innecesarios en la interfaz del revisor.
- [ ] Registrar quién aprobó, cuándo, qué aprobó y qué se ejecutó.
- [ ] Añadir expiración para aprobaciones pendientes.
- [ ] Hacer que una acción aprobada no pueda aprobarse o ejecutarse dos veces.

### Pruebas

- [ ] Email pendiente no aparece como enviado antes de aprobar.
- [ ] Email rechazado nunca llama a la tool.
- [ ] Email aprobado llama a la tool exactamente una vez.
- [ ] Decisión inválida mantiene la acción bloqueada.
- [ ] Repetir la aprobación devuelve el estado final sin repetir la acción.
- [ ] El resumen HITL contiene tool y argumentos normalizados.

### Criterios de aceptación

- Ninguna acción sensible produce efecto lateral antes de la aprobación.
- El control no depende de que el LLM escriba “email enviado”.
- La auditoría permite reconstruir la solicitud, la aprobación y la ejecución.

## Fase 3 — Rate limiting de API y autenticación

**IDs:** SEC-03, API-01  
**Prioridad:** P0  
**Dependencias:** Fase 0

### Implementación

- [ ] Eliminar `reset_user()` del flujo normal de `/chat`.
- [ ] Mantener el reset únicamente en fixtures o utilidades de test.
- [ ] Proteger el contador con lock para concurrencia dentro del proceso.
- [ ] Diseñar backend distribuido para producción, preferiblemente Redis.
- [ ] Aplicar límite separado para login por IP y por usuario.
- [ ] Añadir límites de tamaño y frecuencia a `/chat`.
- [ ] Devolver `429` con `Retry-After`, no una respuesta normal del agente.
- [ ] Hacer `JWT_SECRET` obligatorio fuera de desarrollo.
- [ ] Rechazar secretos conocidos o el secreto demo al arrancar en producción.
- [ ] Migrar passwords a Argon2id o bcrypt con salt.
- [ ] Añadir expiración, issuer, audience y estrategia de revocación de tokens.
- [ ] Evitar revelar si el usuario existe durante login.

### Pruebas

- [ ] Once requests consecutivas del mismo usuario producen `429` después del límite.
- [ ] Requests de dos usuarios no comparten contador.
- [ ] El reset de tests no está disponible mediante endpoint.
- [ ] Doce intentos de login fallidos activan el límite.
- [ ] JWT con firma incorrecta, expirado, issuer incorrecto o audience incorrecta es rechazado.
- [ ] El servicio no arranca en modo producción con secreto demo.

### Criterios de aceptación

- El rate limiting funciona desde la API, no solo en pruebas unitarias.
- El login no permite fuerza bruta básica.
- La configuración insegura de demo no puede llegar accidentalmente a producción.

## Fase 4 — SQL seguro y limitado

**ID:** SEC-04  
**Prioridad:** P0  
**Dependencias:** SEC-01

### Implementación

- [ ] Reemplazar el `pass` de la allowlist por validación efectiva.
- [ ] Permitir únicamente tablas y columnas explícitas.
- [ ] Bloquear `sqlite_master`, `sqlite_sequence`, pragmas y funciones no aprobadas.
- [ ] Rechazar múltiples statements y comentarios peligrosos.
- [ ] Usar conexión SQLite read-only.
- [ ] Activar `set_authorizer` o parser SQL seguro.
- [ ] Añadir `LIMIT` máximo de forma controlada.
- [ ] Configurar timeout de conexión y consulta.
- [ ] No devolver emails, salarios u otras columnas sensibles salvo permiso explícito.
- [ ] Normalizar y validar la respuesta SQL antes de entregarla al LLM.
- [ ] Cerrar conexiones mediante `try/finally` o context manager.

### Pruebas

- [ ] `SELECT` permitido sobre tabla y columnas permitidas.
- [ ] `SELECT` sobre tabla no permitida rechazado.
- [ ] `SELECT` sobre `sqlite_master` rechazado.
- [ ] `DROP`, `DELETE`, `UPDATE`, `INSERT` y stacked queries rechazados.
- [ ] `UNION` hacia tablas no permitidas rechazado.
- [ ] Query muy lenta o sin límite termina por timeout.
- [ ] El resultado nunca supera `MAX_ROWS`.

### Criterios de aceptación

- La tool no ejecuta SQL fuera del contrato permitido aunque el LLM lo solicite.
- La autorización se verifica antes y durante la ejecución.

## Fase 5 — PII, privacidad y prompt injection RAG

**IDs:** SEC-05, SEC-06  
**Prioridad:** P0  
**Dependencias:** Fases 1 y 4

### Protección PII

- [ ] Aplicar `filter_pii()` antes de cada respuesta API y UI.
- [ ] Aplicar redacción antes de guardar traces.
- [ ] Redactar queries, argumentos de tools y payloads HITL según política.
- [ ] No guardar tokens, API keys, passwords ni cuerpos completos de emails.
- [ ] Añadir política de retención y borrado de traces.
- [ ] Registrar solo hashes o identificadores cuando no se necesite el valor original.
- [ ] Añadir detección de IBAN, tarjetas, direcciones y otros datos relevantes.
- [ ] Definir excepciones explícitas para usuarios admin y aun así evitar secretos.

### Prompt injection en documentos

- [ ] Escanear documentos durante ingesta.
- [ ] Marcar o rechazar chunks con instrucciones de sistema, role overrides o secretos.
- [ ] Insertar contexto RAG como datos delimitados, nunca como instrucciones ejecutables.
- [ ] Separar prompt fijo del contexto dinámico.
- [ ] Añadir un validador de fuentes antes de construir el prompt.
- [ ] Añadir threshold de relevancia para responder “no tengo información”.
- [ ] Registrar score de retrieval y decisión de descarte.

### Pruebas

- [ ] Email, teléfono, DNI, salario y API key se redactan en respuesta y trace.
- [ ] PII en una fuente RAG no aparece sin autorización.
- [ ] Documento con `[SYSTEM]`, XML o instrucciones ocultas no modifica la política del agente.
- [ ] Payloads con Unicode confusable, Base64, markdown, HTML y espacios extra son seguros.
- [ ] Pregunta fuera de dominio sin chunks relevantes no produce alucinación.

### Criterios de aceptación

- No existe camino de salida para secretos o PII no autorizada.
- El contenido recuperado no puede cambiar las instrucciones de seguridad.

## Fase 6 — Estado, reintentos e idempotencia del grafo

**IDs:** REL-01, REL-02, REL-03  
**Prioridad:** P1  
**Dependencias:** SEC-02

### Implementación

- [ ] Hacer que el límite de reintentos sea una garantía del router, no del LLM.
- [ ] Incrementar el contador en cada paso que vuelva a un worker.
- [ ] Añadir un guard que corte cualquier loop por encima del máximo.
- [ ] Separar `generation_retry` de `action_retry`.
- [ ] Prohibir reejecutar una acción ya completada.
- [ ] Añadir `idempotency_key` por solicitud y por acción.
- [ ] Guardar estado de tool: no iniciada, ejecutando, completada o fallida.
- [ ] Usar estado estructurado para saber si una acción es email, ticket u otra tool.
- [ ] Definir claramente qué respuestas de baja confianza requieren HITL.
- [ ] No enviar respuestas de baja confianza a un nodo HITL que no pueda interrumpir.

### Pruebas

- [ ] Critic con `confidence < 0.7` y `necesita_reintento=False` no genera loop infinito.
- [ ] El máximo de reintentos se respeta aunque el LLM entregue valores inconsistentes.
- [ ] Un retry de generación no crea otro ticket.
- [ ] Un retry de generación no envía otro email.
- [ ] Una acción fallida puede reanudarse sin duplicarse.
- [ ] Una respuesta de baja confianza termina como HITL real o como rechazo explícito.

### Criterios de aceptación

- Todo loop tiene un límite verificable.
- Toda tool con efecto lateral es idempotente.
- El routing no depende de frases generadas por el LLM.

## Fase 7 — Persistencia de tickets y cola HITL

**IDs:** REL-04, REL-05, REL-06  
**Prioridad:** P1  
**Dependencias:** Fases 2 y 6

### Tickets

- [ ] Elegir SQLite como fuente única inicial o migrar directamente a PostgreSQL.
- [ ] Eliminar la lista global `_tickets_db` y `_next_id`.
- [ ] Añadir propietario, creador, timestamps y estado de auditoría.
- [ ] Aplicar ownership: un empleado solo ve sus tickets salvo política explícita.
- [ ] Hacer que Action Agent y Data Agent consulten la misma fuente.
- [ ] Añadir transacciones y restricciones de integridad.

### HITL

- [ ] Crear una cola persistente de acciones pendientes.
- [ ] Exponer `GET /hitl/pending` autenticado y restringido a admin.
- [ ] Devolver acción, usuario, riesgo, timestamp y estado.
- [ ] Validar que un thread existe, está pendiente y corresponde a una acción HITL.
- [ ] Añadir control de replay y expiración.
- [ ] Registrar aprobación y rechazo en auditoría.
- [ ] Actualizar frontend y Streamlit desde la cola backend, no desde estado local.
- [ ] Mostrar resultado de la ejecución aprobada en el chat original.

### Pruebas

- [ ] Ticket creado aparece igual en Action Agent y Data Agent.
- [ ] Dos procesos no generan el mismo ID.
- [ ] Admin ve pendientes creados por otra sesión.
- [ ] Empleado no puede listar ni resolver pendientes.
- [ ] Thread inexistente, resuelto o expirado devuelve error controlado.
- [ ] Aprobar dos veces no repite la acción.

### Criterios de aceptación

- Existe una sola fuente de verdad para tickets.
- La cola HITL funciona entre procesos y sesiones.
- Cada acción sensible tiene historial auditable.

## Fase 8 — API, JWT, CORS y resiliencia

**IDs:** API-02, API-03  
**Prioridad:** P1  
**Dependencias:** Fases 3 y 7

### Implementación

- [ ] Proteger `/stats` con autenticación y decidir si solo admin puede verlo.
- [ ] Proteger `/hitl/pending` con rol admin.
- [ ] Restringir CORS a dominios configurados.
- [ ] Validar `query` con longitud mínima y máxima.
- [ ] Rechazar input vacío, excesivo o con encoding inválido.
- [ ] Añadir límites de timeout y cancelación a `/chat`.
- [ ] Usar `ainvoke()` o threadpool para no bloquear el event loop.
- [ ] Añadir exception handlers sin devolver detalles internos.
- [ ] No incluir excepciones crudas en respuestas 404/500.
- [ ] Añadir correlation ID a cada request.
- [ ] Registrar el estado final de todas las requests, incluyendo bloqueadas y HITL.
- [ ] Añadir healthcheck de dependencias sin exponer configuración sensible.

### Pruebas

- [ ] CORS rechaza origen no configurado.
- [ ] `/stats` sin token devuelve `401`.
- [ ] `/hitl/pending` para empleado devuelve `403`.
- [ ] Query mayor que el límite devuelve `422`.
- [ ] Error interno no muestra stack trace ni datos de configuración.
- [ ] Requests concurrentes no bloquean completamente la API.

### Criterios de aceptación

- La API tiene contratos claros para `401`, `403`, `409`, `422`, `429` y `500`.
- No hay endpoints sensibles públicos por accidente.

## Fase 9 — Frontend y autenticación de sesión

**IDs:** FE-01, FE-02  
**Prioridad:** P1  
**Dependencias:** Fase 8

### Implementación

- [ ] Eliminar el puente global `window.__addPending`.
- [ ] Leer pendientes desde el endpoint backend con React Query.
- [ ] Invalidar la cola después de aprobar o rechazar.
- [ ] Mostrar estados loading, empty, error y stale.
- [ ] Cerrar sesión automáticamente ante `401`.
- [ ] Validar token con `/me` al restaurar la sesión.
- [ ] Manejar JSON corrupto en `localStorage` sin romper el provider.
- [ ] Evaluar migración del token a cookie HttpOnly.
- [ ] Corregir el `setState` dentro de effect según las reglas de React.
- [ ] Eliminar imports, variables y props no utilizados.
- [ ] Añadir `npm run lint` y `npm run build` a CI.

### Pruebas

- [ ] La página HITL muestra pendientes de otra sesión.
- [ ] La página desaparece o redirige correctamente cuando el usuario no es admin.
- [ ] Token expirado limpia la sesión y redirige a login.
- [ ] `localStorage` corrupto no deja la aplicación en pantalla blanca.
- [ ] Lint sin errores ni warnings nuevos.
- [ ] Build de producción exitoso.

### Criterios de aceptación

- La interfaz refleja el estado real del backend.
- La sesión no depende de datos manipulables del navegador para autorizar acciones.

## Fase 10 — Evals y Red Teaming deterministas

**IDs:** QA-01, QA-02  
**Prioridad:** P1  
**Dependencias:** Fases 1 a 9

### Implementación

- [ ] Convertir scripts de prueba en suite `pytest` con assertions.
- [ ] Validar `expected_source`, no solo keywords de respuesta.
- [ ] Aplicar constraints `0 <= score <= 1` y `Literal` para categorías.
- [ ] Separar métricas de clasificación, respuesta, seguridad y ejecución.
- [ ] Añadir mocks de LLM para pruebas unitarias sin coste.
- [ ] Añadir pruebas de integración con tools instrumentadas.
- [ ] Registrar si una tool fue llamada y con qué argumentos.
- [ ] Red Team evaluator debe comprobar efectos laterales, no solo texto.
- [ ] Añadir ataques de Unicode, Base64, RAG poisoning, tool chaining y replay.
- [ ] Ejecutar evals con ambos modelos: configuración híbrida y fallback.
- [ ] Definir thresholds de regresión por categoría.
- [ ] Fallar CI si cae seguridad, autorización o exactitud bajo el baseline.

### Pruebas mínimas nuevas

- [ ] Empleado no puede ejecutar email.
- [ ] Email no se ejecuta antes de aprobación.
- [ ] Email aprobado se ejecuta una sola vez.
- [ ] Rate limit de API bloquea la request número 11.
- [ ] SQL fuera de allowlist no se ejecuta.
- [ ] PII no aparece en respuesta ni trace.
- [ ] Documento RAG malicioso no altera el system prompt.
- [ ] Reintento no duplica efectos laterales.
- [ ] Tickets de acción y SQL son consistentes.
- [ ] Pendientes HITL son visibles cross-session.

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

- [ ] RBAC probado a nivel de intención y tool.
- [ ] Email nunca se ejecuta antes de aprobación.
- [ ] SQL read-only y allowlist efectiva.
- [ ] Rate limit probado desde API y login.
- [ ] PII redactada en respuesta, fuentes, HITL y logs.
- [ ] RAG poisoning probado.
- [ ] JWT secret no usa valor demo.
- [ ] CORS restringido.
- [ ] Docker no contiene secretos.

### Fiabilidad

- [ ] No hay loops infinitos.
- [ ] No hay duplicados por retries.
- [ ] Tickets tienen una fuente de verdad.
- [ ] HITL persiste entre sesiones/procesos.
- [ ] Aprobaciones son idempotentes.
- [ ] Tracing incluye bloqueos, pausas y decisiones.

### Calidad

- [ ] Python compileall pasa.
- [ ] Tests unitarios pasan.
- [ ] Tests de integración pasan.
- [ ] Evals no caen bajo baseline.
- [ ] Red Teaming no detecta brechas.
- [ ] Frontend lint pasa.
- [ ] Frontend build pasa.
- [ ] Docker build pasa.
- [ ] README y documentación reflejan el comportamiento real.

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

