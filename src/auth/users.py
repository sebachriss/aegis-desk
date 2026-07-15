"""Usuarios de prueba para Aegis Desk.

En producción, esto vendría de una DB real.
Por ahora, usuarios hardcodeados con passwords hasheadas.
"""

import hashlib


def _hash(password: str) -> str:
    """Hash simple con SHA-256 (suficiente para demo educativo)."""
    return hashlib.sha256(password.encode()).hexdigest()


# Usuarios: username -> {password_hash, role, display_name}
USERS = {
    "ana.garcia": {
        "password_hash": _hash("ana123"),
        "role": "empleado",
        "display_name": "Ana García",
    },
    "carlos.lopez": {
        "password_hash": _hash("carlos123"),
        "role": "empleado",
        "display_name": "Carlos López",
    },
    "admin.aegis": {
        "password_hash": _hash("admin123"),
        "role": "admin",
        "display_name": "Admin Aegis",
    },
}


def authenticate(username: str, password: str) -> dict | None:
    """Verifica credenciales y devuelve el usuario si son correctas.

    Returns:
        Dict con username, role, display_name si autentica, None si no.
    """
    user = USERS.get(username)
    if user is None:
        return None
    if user["password_hash"] != _hash(password):
        return None
    return {
        "username": username,
        "role": user["role"],
        "display_name": user["display_name"],
    }


def get_user(username: str) -> dict | None:
    """Devuelve info del usuario por username (sin password)."""
    user = USERS.get(username)
    if user is None:
        return None
    return {
        "username": username,
        "role": user["role"],
        "display_name": user["display_name"],
    }
