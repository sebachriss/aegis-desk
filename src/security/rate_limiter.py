"""Rate limiter: limites de requests por usuario y por IP para login.

Evita que un usuario haga spam de consultas al LLM y que un atacante
haga fuerza bruta sobre el endpoint de login.
"""

import time
from collections import defaultdict

# {user_id: [timestamp1, timestamp2, ...]}
_requests: dict[str, list[float]] = defaultdict(list)
_login_attempts: dict[str, list[float]] = defaultdict(list)

# Configuracion de chat
MAX_REQUESTS = 10        # maximo de requests
WINDOW_SECONDS = 120     # en una ventana de 120 segundos
COOLDOWN_SECONDS = 60    # si se excede, esperar 60s antes de permitir mas

# Configuracion de login
MAX_LOGIN_ATTEMPTS = 12       # maximo de intentos fallidos de login
LOGIN_WINDOW_SECONDS = 900  # ventana de 15 minutos


def _clean_window(timestamps: list[float], window: int) -> list[float]:
    """Elimina timestamps anteriores a la ventana actual."""
    now = time.time()
    cutoff = now - window
    return [ts for ts in timestamps if ts > cutoff]


def check_rate_limit(user_id: str) -> dict:
    """Verifica si un usuario puede hacer otra request de chat.

    Args:
        user_id: Identificador del usuario.

    Returns:
        Diccionario con:
          - allowed: True si puede hacer la request
          - reason: Motivo si no se permite
          - requests_in_window: Cuantas requests hizo en la ventana actual
          - limit: Limite configurado
    """
    now = time.time()

    # Limpiar timestamps fuera de la ventana
    _requests[user_id] = _clean_window(_requests[user_id], WINDOW_SECONDS)

    # Contar requests actuales en la ventana
    current_count = len(_requests[user_id])

    if current_count >= MAX_REQUESTS:
        # Calcular cuando podra hacer otra request
        oldest_in_window = _requests[user_id][0]
        retry_after = int(oldest_in_window + WINDOW_SECONDS - now)
        return {
            "allowed": False,
            "reason": f"Rate limit excedido: {current_count}/{MAX_REQUESTS} requests en {WINDOW_SECONDS}s. Intenta en {retry_after}s.",
            "requests_in_window": current_count,
            "limit": MAX_REQUESTS,
        }

    # Registrar esta request
    _requests[user_id].append(now)

    return {
        "allowed": True,
        "reason": None,
        "requests_in_window": current_count + 1,
        "limit": MAX_REQUESTS,
    }


def check_login_rate_limit(ip_or_username: str) -> dict:
    """Verifica si una IP/usuario puede intentar login.

    Args:
        ip_or_username: IP del cliente o username (para rate limit por usuario).

    Returns:
        Diccionario con allowed, reason, attempts_in_window, limit.
    """
    now = time.time()
    _login_attempts[ip_or_username] = _clean_window(
        _login_attempts[ip_or_username], LOGIN_WINDOW_SECONDS
    )
    current_count = len(_login_attempts[ip_or_username])

    if current_count >= MAX_LOGIN_ATTEMPTS:
        oldest = _login_attempts[ip_or_username][0]
        retry_after = int(oldest + LOGIN_WINDOW_SECONDS - now)
        return {
            "allowed": False,
            "reason": f"Demasiados intentos de login: {current_count}/{MAX_LOGIN_ATTEMPTS}. Intenta en {retry_after}s.",
            "attempts_in_window": current_count,
            "limit": MAX_LOGIN_ATTEMPTS,
        }

    _login_attempts[ip_or_username].append(now)
    return {
        "allowed": True,
        "reason": None,
        "attempts_in_window": current_count + 1,
        "limit": MAX_LOGIN_ATTEMPTS,
    }


def reset_user(user_id: str) -> None:
    """Resetea el contador de un usuario (para tests o admin override).

    Esta funcion NO debe usarse en el flujo normal de /chat.
    """
    _requests[user_id] = []


def reset_login(ip_or_username: str) -> None:
    """Resetea los intentos de login de una IP o usuario (para tests)."""
    _login_attempts[ip_or_username] = []
