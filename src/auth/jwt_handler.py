"""Manejo de JWT tokens para Aegis Desk.

Funciones:
  - create_access_token(user) -> token JWT
  - verify_token(token) -> payload decodificado o None
  - get_current_user(token) -> dict con info del usuario

Fase 3 (SEC-03):
  - JWT_SECRET no puede ser el valor demo en produccion.
  - Tokens incluyen issuer y audience claims.
  - Tokens sin rol explicito son rechazados.
"""

import time
import hmac
import hashlib
import base64
import json

from src.config import get_settings


def _get_jwt_secret() -> str:
    """Obtiene el secret para firmar JWT desde settings.

    En produccion, rechaza el secreto de demo.
    """
    settings = get_settings()
    secret = getattr(settings, "jwt_secret", None)
    environment = getattr(settings, "environment", "development")

    demo_secrets = {
        "aegis-desk-demo-secret-change-in-production",
        "",
        None,
    }

    if environment == "production" and secret in demo_secrets:
        raise RuntimeError(
            "JWT_SECRET no puede usar el secreto demo en produccion. "
            "Configura una variable de entorno segura."
        )

    if not secret:
        # En desarrollo, permitir un fallback controlado para facilitar tests
        if environment == "production":
            raise RuntimeError("JWT_SECRET es obligatorio en produccion.")
        return "aegis-desk-demo-secret-change-in-production"

    return secret


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
        expires_in_seconds: Tiempo de expiracion del token.

    Returns:
        Token JWT codificado como string.
    """
    settings = get_settings()
    secret = _get_jwt_secret()
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "name": user["display_name"],
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + expires_in_seconds,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    message = f"{header_b64}.{payload_b64}"
    signature = _sign(message, secret)

    return f"{message}.{signature}"


def verify_token(token: str) -> dict | None:
    """Verifica un JWT token y devuelve el payload si es valido.

    Returns:
        Payload decodificado si el token es valido y no ha expirado, None si no.
    """
    if not token or token.count(".") != 2:
        return None

    settings = get_settings()
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

    # Verificar expiracion
    if payload.get("exp", 0) < int(time.time()):
        return None

    # Verificar issuer y audience
    if payload.get("iss") != settings.jwt_issuer:
        return None
    if payload.get("aud") != settings.jwt_audience:
        return None

    return payload


def get_current_user(token: str) -> dict | None:
    """Extrae info del usuario desde un token valido.

    Rechaza tokens sin campo 'role' explicito.

    Returns:
        Dict con username, role, display_name si el token es valido, None si no.
    """
    payload = verify_token(token)
    if payload is None:
        return None

    role = payload.get("role")
    if not role:
        return None

    return {
        "username": payload.get("sub", ""),
        "role": role,
        "display_name": payload.get("name", ""),
    }
