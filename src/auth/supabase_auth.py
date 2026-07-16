"""Autenticacion opcional con Supabase Auth.

Se usa solo si SUPABASE_URL y SUPABASE_KEY estan configurados y el usuario
introduce un email como username. En caso de fallo, el sistema vuelve al
auth local de src.auth.users.
"""

from __future__ import annotations

from src.db.supabase_client import get_supabase_client, is_supabase_configured


def authenticate_with_supabase(email: str, password: str) -> dict | None:
    """Autentica contra Supabase Auth y devuelve info de usuario para JWT.

    Returns:
        dict con username (email), role, display_name, o None si falla.
    """
    if not is_supabase_configured():
        return None

    try:
        client = get_supabase_client()
        response = client.auth.sign_in_with_password({"email": email, "password": password})
        user = response.user
        if not user:
            return None

        role = "empleado"
        display_name = email
        metadata = user.user_metadata or {}
        if metadata.get("role") in ("admin", "empleado"):
            role = metadata["role"]
        if metadata.get("display_name"):
            display_name = metadata["display_name"]

        return {
            "username": email,
            "role": role,
            "display_name": display_name,
        }
    except Exception:
        return None
