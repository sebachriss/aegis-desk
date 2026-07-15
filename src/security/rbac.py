"""Control de acceso basado en roles (RBAC).

Define qué herramientas puede usar cada rol.
El supervisor o el grafo consulta esto antes de dar tools a un agente.

Roles:
  - empleado: RAG, chat, tickets (crear/listar/buscar), NO SQL, NO email
  - admin: todo lo de empleado + SQL + email
"""

from src.tools.registry import TOOLS

# Permisos por rol: lista de nombres de tools permitidas
ROLE_PERMISSIONS = {
    "empleado": [
        "crear_ticket",
        "listar_tickets",
        "buscar_ticket",
    ],
    "admin": [
        "crear_ticket",
        "listar_tickets",
        "buscar_ticket",
        "enviar_email",
        "consultar_sql",
    ],
}

# Intenciones permitidas por rol (qué workers puede usar)
ROLE_INTENTIONS = {
    "empleado": ["rag", "accion", "chat"],
    "admin": ["rag", "datos", "accion", "chat"],
}


def get_allowed_tools(role: str) -> list:
    """Devuelve las herramientas permitidas para un rol.

    Args:
        role: "empleado" o "admin"

    Returns:
        Lista de funciones @tool permitidas para ese rol.
    """
    allowed_names = ROLE_PERMISSIONS.get(role, [])
    return [TOOLS[name] for name in allowed_names if name in TOOLS]


def get_allowed_intentions(role: str) -> list[str]:
    """Devuelve las intenciones (workers) permitidas para un rol.

    Args:
        role: "empleado" o "admin"

    Returns:
        Lista de intenciones permitidas: ["rag", "accion", "chat", ...]
    """
    return ROLE_INTENTIONS.get(role, ["chat"])


def can_access(role: str, intention: str) -> bool:
    """Verifica si un rol puede acceder a una intención (worker).

    Args:
        role: "empleado" o "admin"
        intention: "rag", "datos", "accion", o "chat"

    Returns:
        True si el rol tiene permiso, False si no.
    """
    allowed = get_allowed_intentions(role)
    return intention in allowed
