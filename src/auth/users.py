"""Usuarios de prueba para Aegis Desk.

En produccion, esto vendria de una DB real.
Por ahora, usuarios hardcodeados con passwords hasheadas con bcrypt.
"""

import bcrypt


def _hash(password: str) -> str:
    """Hash seguro con bcrypt y salt automatico."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify(password: str, password_hash: str) -> bool:
    """Verifica un password contra un hash bcrypt."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


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

    No revela si el usuario existe o la contraseña es incorrecta.

    Returns:
        Dict con username, role, display_name si autentica, None si no.
    """
    user = USERS.get(username)
    if user is None:
        return None
    if not _verify(password, user["password_hash"]):
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
