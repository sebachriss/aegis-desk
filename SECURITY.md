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
- Email whitelist (solo dominios internos)
- SQL allowlist (solo SELECT)
- PII filter (enmascara datos sensibles)
- `.env` excluido del repo via `.gitignore`

## Red Teaming

El proyecto incluye una suite de red teaming automatizada:

```bash
python -m redteam.run_redteam --save
```

Resultado actual: 31/31 ataques defendidos (100% defense rate).

Cualquier cambio que afecte seguridad debe pasar esta suite antes de merge.
