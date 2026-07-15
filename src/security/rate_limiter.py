"""Rate limiter: límite de requests por usuario en ventana de tiempo.

Evita que un usuario haga spam de consultas al LLM.
Usa una ventana deslizante: cuenta requests en los últimos N segundos.
"""

import time
from collections import defaultdict

# {user_id: [timestamp1, timestamp2, ...]}
_requests: dict[str, list[float]] = defaultdict(list)

# Configuración
MAX_REQUESTS = 10        # máximo de requests
WINDOW_SECONDS = 120     # en una ventana de 120 segundos
COOLDOWN_SECONDS = 60    # si se excede, esperar 60s antes de permitir más


def check_rate_limit(user_id: str) -> dict:
    """Verifica si un usuario puede hacer otra request.

    Limpia timestamps viejos, cuenta los recientes, y decide.

    Args:
        user_id: Identificador del usuario.

    Returns:
        Diccionario con:
          - allowed: True si puede hacer la request
          - reason: Motivo si no se permite
          - requests_in_window: Cuántas requests hizo en la ventana actual
          - limit: Límite configurado
    """
    now = time.time()

    # Limpiar timestamps fuera de la ventana
    cutoff = now - WINDOW_SECONDS
    _requests[user_id] = [ts for ts in _requests[user_id] if ts > cutoff]

    # Contar requests actuales en la ventana
    current_count = len(_requests[user_id])

    if current_count >= MAX_REQUESTS:
        # Calcular cuándo podrá hacer otra request
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


def reset_user(user_id: str) -> None:
    """Resetea el contador de un usuario (para tests o admin override)."""
    _requests[user_id] = []
