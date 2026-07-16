"""Nodo de seguridad: guardrails antes del supervisor.

Ejecuta antes que el supervisor y verifica:
1. Prompt injection → bloquear si se detecta
2. Rate limiting → bloquear si se excede
3. RBAC → marcar el rol del usuario en el estado

Si algo falla, devuelve una respuesta de rechazo y termina el flujo.
"""

from src.agents.state import AgentState
from src.security.prompt_injection import detect_prompt_injection, sanitize_input
from src.security.rbac import validate_role
from src.security.rate_limiter import check_rate_limit


def security_node(state: AgentState) -> dict:
    """Nodo del grafo: verifica seguridad antes de procesar la request.

    Lee state["query"] y state["user_id"] (si existe), verifica:
    - Prompt injection
    - Rate limit
    - Rol válido
    - Sanitiza el input

    Si detecta un problema, devuelve respuesta de rechazo y marca para terminar.
    """
    query = state["query"]
    user_id = state.get("user_id", "default")
    role = state.get("role")

    # 1. Validar rol explícito (fail closed)
    if not role or not validate_role(role):
        return {
            "respuesta": "⛔ Rol inválido o no especificado. Contacta al administrador.",
            "confidence": 1.0,
            "requires_human_review": False,
            "intencion": "bloqueado",
            "authorization_decision": "unknown_role",
        }

    # 2. Detectar prompt injection
    injection_check = detect_prompt_injection(query)
    if injection_check["is_injection"]:
        return {
            "respuesta": f"⚠️ Solicitud bloqueada: se detectó un posible intento de manipulación. Si crees que es un error, contacta al administrador.",
            "confidence": 1.0,
            "requires_human_review": False,
            "intencion": "bloqueado",
        }

    # 2. Rate limiting
    rate_check = check_rate_limit(user_id)
    if not rate_check["allowed"]:
        return {
            "respuesta": f"⏳ {rate_check['reason']}",
            "confidence": 1.0,
            "requires_human_review": False,
            "intencion": "bloqueado",
        }

    # 3. Sanitizar input (quitar etiquetas peligrosas)
    sanitized_query = sanitize_input(query)

    # Si el input cambió tras sanitización, usar la versión limpia
    return {
        "query": sanitized_query,
    }
