"""Rate limiter: limites de requests por usuario y por IP para login.

Evita que un usuario haga spam de consultas al LLM y que un atacante
haga fuerza bruta sobre el endpoint de login.
"""

import time
import threading
from collections import defaultdict

# Proteger contadores contra race conditions en el mismo proceso
_ratelimit_lock = threading.Lock()

# {user_id: [timestamp1, timestamp2, ...]}
_requests: dict[str, list[float]] = defaultdict(list)
_login_attempts_ip: dict[str, list[float]] = defaultdict(list)
_login_attempts_user: dict[str, list[float]] = defaultdict(list)

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

    with _ratelimit_lock:
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
                "retry_after": retry_after,
            }

        # Registrar esta request
        _requests[user_id].append(now)

        return {
            "allowed": True,
            "reason": None,
            "requests_in_window": current_count + 1,
            "limit": MAX_REQUESTS,
            "retry_after": 0,
        }


def _is_allowed(store: dict, key: str, max_attempts: int, window: int) -> tuple[bool, list[float]]:
    """Devuelve si se permite otro intento y la ventana actual limpia."""
    with _ratelimit_lock:
        store[key] = _clean_window(store[key], window)
        return len(store[key]) < max_attempts, store[key]


def _record_attempt(store: dict, key: str, now: float) -> None:
    """Registra un intento (después de verificar ambos límites)."""
    with _ratelimit_lock:
        store[key].append(now)


def check_login_rate_limit(ip: str, username: str = "") -> dict:
    """Verifica si una IP y/o usuario pueden intentar login.

    Aplica límites separados por IP y por nombre de usuario. Solo registra
    el intento si ambos límites permiten continuar.

    Args:
        ip: IP del cliente.
        username: Nombre de usuario (opcional). Se aplica un segundo rate limit.

    Returns:
        Diccionario con allowed, reason, attempts_in_window, limit.
    """
    now = time.time()

    ip_allowed, ip_window = _is_allowed(
        _login_attempts_ip, ip, MAX_LOGIN_ATTEMPTS, LOGIN_WINDOW_SECONDS
    )
    if not ip_allowed:
        retry_after = int(ip_window[0] + LOGIN_WINDOW_SECONDS - now)
        current_count = len(ip_window)
        return {
            "allowed": False,
            "reason": f"Demasiados intentos de login desde esta IP: {current_count}/{MAX_LOGIN_ATTEMPTS}. Intenta en {retry_after}s.",
            "attempts_in_window": current_count,
            "limit": MAX_LOGIN_ATTEMPTS,
            "retry_after": retry_after,
        }

    if username:
        user_allowed, user_window = _is_allowed(
            _login_attempts_user, username, MAX_LOGIN_ATTEMPTS, LOGIN_WINDOW_SECONDS
        )
        if not user_allowed:
            retry_after = int(user_window[0] + LOGIN_WINDOW_SECONDS - now)
            current_count = len(user_window)
            return {
                "allowed": False,
                "reason": f"Demasiados intentos de login para este usuario: {current_count}/{MAX_LOGIN_ATTEMPTS}. Intenta en {retry_after}s.",
                "attempts_in_window": current_count,
                "limit": MAX_LOGIN_ATTEMPTS,
                "retry_after": retry_after,
            }

    _record_attempt(_login_attempts_ip, ip, now)
    if username:
        _record_attempt(_login_attempts_user, username, now)

    return {
        "allowed": True,
        "reason": None,
        "attempts_in_window": len(_login_attempts_ip[ip]),
        "limit": MAX_LOGIN_ATTEMPTS,
        "retry_after": 0,
    }


def reset_user(user_id: str) -> None:
    """Resetea el contador de un usuario (para tests o admin override).

    Esta funcion NO debe usarse en el flujo normal de /chat.
    """
    _requests[user_id] = []


def reset_login(ip_or_username: str) -> None:
    """Resetea los intentos de login de una IP o usuario (para tests)."""
    with _ratelimit_lock:
        if ip_or_username in _login_attempts_ip:
            _login_attempts_ip[ip_or_username] = []
        if ip_or_username in _login_attempts_user:
            _login_attempts_user[ip_or_username] = []
