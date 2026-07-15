"""Manejo de JWT tokens para Aegis Desk.

Funciones:
  - create_access_token(user) → token JWT
  - verify_token(token) → payload decodificado o None
  - get_current_user(token) → dict con info del usuario
"""

import time
import hmac
import hashlib
import base64
import json

from src.config import get_settings


def _get_jwt_secret() -> str:
    """Obtiene el secret para firmar JWT desde settings o usa un default de demo."""
    settings = get_settings()
    secret = getattr(settings, "jwt_secret", None)
    if secret:
        return secret
    return "aegis-desk-demo-secret-change-in-production"


def _base64url_encode(data: bytes) -> str:
    """Codifica bytes a base64url sin padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _base64url_decode(data: str) -> bytes:
    """Decodifica base64url a bytes."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _sign(message: str, secret: str) -> str:
    """Firma un mensaje con HMAC-SHA256."""
    return _base64url_encode(
        hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    )


def create_access_token(user: dict, expires_in_seconds: int = 3600) -> str:
    """Crea un JWT token para el usuario.

    Args:
        user: Dict con username, role, display_name.
        expires_in_seconds: Tiempo de expiración del token.

    Returns:
        Token JWT codificado como string.
    """
    secret = _get_jwt_secret()
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "name": user["display_name"],
        "iat": now,
        "exp": now + expires_in_seconds,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    message = f"{header_b64}.{payload_b64}"
    signature = _sign(message, secret)

    return f"{message}.{signature}"


def verify_token(token: str) -> dict | None:
    """Verifica un JWT token y devuelve el payload si es válido.

    Returns:
        Payload decodificado si el token es válido y no ha expirado, None si no.
    """
    if not token or token.count(".") != 2:
        return None

    secret = _get_jwt_secret()
    header_b64, payload_b64, signature = token.split(".")

    # Verificar firma
    message = f"{header_b64}.{payload_b64}"
    expected_signature = _sign(message, secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    # Decodificar payload
    try:
        payload = json.loads(_base64url_decode(payload_b64))
    except (json.JSONDecodeError, Exception):
        return None

    # Verificar expiración
    if payload.get("exp", 0) < int(time.time()):
        return None

    return payload


def get_current_user(token: str) -> dict | None:
    """Extrae info del usuario desde un token válido.

    Returns:
        Dict con username, role, display_name si el token es válido, None si no.
    """
    payload = verify_token(token)
    if payload is None:
        return None
    return {
        "username": payload.get("sub", ""),
        "role": payload.get("role", "empleado"),
        "display_name": payload.get("name", ""),
    }
