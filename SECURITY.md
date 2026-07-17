# Security Policy — Aegis Desk

## Versiones soportadas

| Versión | Soporte |
|---|---|
| 1.0.x | ✅ |

## Reportar una vulnerabilidad

Si encuentras una vulnerabilidad de seguridad en Aegis Desk, **por favor no abras un issue público**.

### Proceso

1. Envía un email a: sebachriss@users.noreply.github.com (o abre un [Security Advisory privado](https://github.com/sebachriss/aegis-desk/security/advisories/new))
2. Incluye:
   - Descripción del problema
   - Pasos para reproducir
   - Impacto potencial
   - Sugerencia de fix (si tienes una)
3. Recibirás confirmación dentro de 48 horas
4. Trabajaremos juntos en el fix antes de cualquier publicación pública

### Scope

Vulnerabilidades en scope:
- Bypass de seguridad (prompt injection, RBAC, rate limit)
- Fuga de información sensible (system prompt, API keys, datos de usuarios)
- Injection attacks (SQL, command, etc.)
- Bugs que permitan ejecutar acciones sin HITL
- Configuraciones inseguras de Supabase/Postgres (RLS, secrets en imágenes, etc.)

Fuera de scope:
- El proyecto usa tools simuladas (no hay riesgo real de envío de emails o modificación de DBs externas)
- Ataques que requieran acceso físico al servidor

## Medidas de seguridad implementadas

Aegis Desk implementa defense-in-depth con 4 capas:

1. **Security Node**: detección de prompt injection + rate limiting
2. **RBAC**: control de acceso por rol (empleado vs admin)
3. **LLM Refusal**: prompts endurecidos contra jailbreaks
4. **HITL**: aprobación humana para acciones sensibles

Adicionalmente:
- SQL allowlist explícita de tablas y columnas (solo `SELECT`)
- Rate limiting separado para login por IP y por usuario
- JWT con expiración, issuer, audience y revocación en logout (`jti` + blacklist)
- PII filter (enmascara datos sensibles) y redacción en trazas
- Trace retention policy: límite de edad/cantidad y hashing de identificadores (`user_id`, `approved_by`)
- Email whitelist (solo dominios internos)
- `.env` excluido del repo via `.gitignore`
- Contraseñas hasheadas con bcrypt
- JWT almacenado en cookie `HttpOnly`

- Bloqueo de intentos de bypass HITL/replay (`vuelve a ejecutar`, `sin pedir aprobación`, `reenviar email`).
- Bloqueo de exfiltración a dominios externos y tool chaining (`external@attacker.com`, `listado de empleados`, `primero ... y luego ...`).
- `consultar_sql` expuesto como `StructuredTool` para agentes y como función callable para tests/CLI.

## Seguridad en Supabase

- **RLS habilitado** en todas las tablas `public` (`empleados`, `departamentos`, `tickets`, `hitl_queue`, `document_embeddings`, tablas de checkpointer).
- **Extensión `vector`** ubicada en el schema `extensions` (best practice de Supabase).
- **Conexión directa** a Postgres usa `DATABASE_URL` con usuario `postgres` (owner) y service key solo para operaciones admin/migraciones.
- **Percent-encoding** recomendado en `DATABASE_URL` para `$`, `@` y `%` cuando se usa con Docker Compose.
- `SUPABASE_SERVICE_KEY` y `SUPABASE_KEY` nunca se escriben en código; se inyectan via `.env`.

## Red Teaming

El proyecto incluye una suite de red teaming automatizada:

```bash
python -m redteam.run_redteam --save
```

Resultado actual: 36/36 ataques defendidos (100% defense rate).

Cualquier cambio que afecte seguridad debe pasar esta suite antes de merge.
