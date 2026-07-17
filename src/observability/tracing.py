"""Tracing de ejecuciones del grafo.

Registra cada ejecución con:
  - Query del usuario
  - Intención clasificada
  - Respuesta final
  - Confidence del crítico
  - Tiempo total
  - Fuentes usadas
  - Número de reintentos

Sin LangSmith/Langfuse (no requieren setup externo).
Los traces se guardan en data/traces.jsonl (JSON Lines, una línea por ejecución).

Para usar LangSmith en el futuro:
  1. pip install langsmith
  2. Set LANGSMITH_API_KEY en .env
  3. Set LANGSMITH_TRACING=true en .env
  LangChain auto-tracea si esas vars están seteadas.
"""

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.config import get_settings
from src.security.pii_filter import filter_pii

TRACES_PATH = Path(__file__).parent.parent.parent / "data" / "traces.jsonl"

# Política de retención de traces
MAX_TRACES = 1000
TRACE_RETENTION_DAYS = 30

_trace_lock = threading.Lock()


def _hash_identifier(value: str) -> str:
    """Genera un hash determinista de un identificador para traces.

    Usa HMAC-SHA256 con el JWT_SECRET, truncado a 16 caracteres hex.
    Es reversible solo por quien posea el secret y el diccionario de usuarios.
    """
    if not value:
        return value
    secret = getattr(get_settings(), "jwt_secret", None) or "aegis-trace-secret"
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]


def _sanitize_action_plan(action_plan: dict | None) -> dict | None:
    """Redacta argumentos sensibles de un action_plan antes de guardarlo en trace."""
    if not action_plan:
        return None
    plan = dict(action_plan)
    args = plan.get("arguments")
    if isinstance(args, dict):
        sanitized = {}
        for k, v in args.items():
            key_lower = k.lower()
            if key_lower in {"password", "token", "api_key", "apikey", "secret", "passwd", "cuerpo", "asunto"}:
                sanitized[k] = "***"
            elif plan.get("tool_name") == "enviar_email" and key_lower != "para":
                sanitized[k] = "***"
            elif isinstance(v, str):
                sanitized[k], _ = filter_pii(v)
            else:
                sanitized[k] = v
        plan["arguments"] = sanitized

    # Evitar almacenar IDs de usuario en texto plano en traces
    for key in ("requested_by", "approved_by"):
        if plan.get(key):
            plan[key] = _hash_identifier(plan[key])
    return plan


def trace_execution(
    query: str,
    intencion: str,
    respuesta: str,
    confidence: float,
    fuentes: list[dict],
    retries: int,
    elapsed_seconds: float,
    user_id: str = "unknown",
    role: str = "empleado",
    tool_name: str | None = None,
    authorization_decision: str | None = None,
    action_plan: dict | None = None,
    approved_by: str | None = None,
    approved_at: str | None = None,
    retrieval_scores: list[float] | None = None,
    discarded: int | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Registra una ejecución del grafo en el archivo de traces.

    Args:
        query: Pregunta del usuario.
        intencion: Intención clasificada por el supervisor.
        respuesta: Respuesta final del agente.
        confidence: Confidence del crítico (0-1).
        fuentes: Fuentes usadas (chunks RAG, DB, etc.).
        retries: Número de reintentos.
        elapsed_seconds: Tiempo total de ejecución.
        user_id: ID del usuario.
        role: Rol del usuario.
        tool_name: Nombre de la tool invocada (si aplica).
        authorization_decision: Decisión de autorización ("allowed", "denied", etc.).
        action_plan: Plan de acción estructurado (Fase 2 HITL).
        approved_by: Usuario que aprobó una acción HITL.
        approved_at: Timestamp de aprobación HITL.
        retrieval_scores: Scores de similitud de los chunks recuperados (RAG).
        discarded: Chunks descartados por baja relevancia/fuente inválida (RAG).
        correlation_id: ID de correlación de la request.

    Returns:
        Diccionario con el trace registrado.
    """
    redacted_query, _ = filter_pii(query)
    redacted_respuesta, _ = filter_pii(respuesta)
    trace = {
        "timestamp": datetime.now().isoformat(),
        "user_hash": _hash_identifier(user_id),
        "role": role,
        "query": redacted_query,
        "intencion": intencion,
        "respuesta": redacted_respuesta,
        "confidence": confidence,
        "fuentes_count": len(fuentes),
        "fuentes": [f.get("source", "desconocido") for f in fuentes],
        "retries": retries,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "tool_name": tool_name,
        "authorization_decision": authorization_decision,
        "action_plan": _sanitize_action_plan(action_plan),
        "approved_by_hash": _hash_identifier(approved_by),
        "approved_at": approved_at,
        "retrieval_scores": retrieval_scores,
        "discarded": discarded,
        "correlation_id": correlation_id,
    }

    # Append al archivo JSONL (una línea por trace) y aplicar retención
    TRACES_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _trace_lock:
        with open(TRACES_PATH, "a") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
        _trim_traces()

    return trace


def _trim_traces() -> None:
    """Rota el archivo de traces por antigüedad y cantidad máxima."""
    if not TRACES_PATH.exists():
        return

    cutoff = (datetime.now() - timedelta(days=TRACE_RETENTION_DAYS)).isoformat()

    with open(TRACES_PATH) as f:
        lines = f.readlines()

    valid = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("timestamp", "") >= cutoff:
            valid.append(line)

    if len(valid) > MAX_TRACES:
        valid = valid[-MAX_TRACES:]

    with open(TRACES_PATH, "w") as f:
        for line in valid:
            f.write(line + "\n")


def load_traces(limit: int = 100) -> list[dict]:
    """Carga los traces del archivo JSONL.

    Args:
        limit: Máximo número de traces a cargar (los más recientes).

    Returns:
        Lista de traces, los más recientes primero.
    """
    if not TRACES_PATH.exists():
        return []

    traces = []
    with open(TRACES_PATH) as f:
        for line in f:
            if line.strip():
                traces.append(json.loads(line))

    # Devolver los más recientes primero
    return list(reversed(traces))[:limit]


def get_stats() -> dict:
    """Calcula estadísticas agregadas de los traces.

    Returns:
        Diccionario con stats: total, por intención, avg confidence, avg tiempo.
    """
    traces = load_traces(limit=10000)

    if not traces:
        return {"total": 0}

    stats = {
        "total": len(traces),
        "by_intencion": {},
        "avg_confidence": 0.0,
        "avg_elapsed": 0.0,
        "total_retries": 0,
        "blocked": 0,
    }

    confidences = []
    elapsed = []

    for trace in traces:
        intencion = trace.get("intencion", "unknown")

        if intencion not in stats["by_intencion"]:
            stats["by_intencion"][intencion] = {"count": 0, "avg_confidence": 0.0}

        stats["by_intencion"][intencion]["count"] += 1

        if trace.get("confidence"):
            confidences.append(trace["confidence"])

        if trace.get("elapsed_seconds"):
            elapsed.append(trace["elapsed_seconds"])

        stats["total_retries"] += trace.get("retries", 0)

        if intencion == "bloqueado":
            stats["blocked"] += 1

    stats["avg_confidence"] = round(sum(confidences) / len(confidences), 3) if confidences else 0
    stats["avg_elapsed"] = round(sum(elapsed) / len(elapsed), 3) if elapsed else 0

    # Calcular avg confidence por intención
    for intencion, data in stats["by_intencion"].items():
        int_confidences = [t["confidence"] for t in traces
                           if t.get("intencion") == intencion and t.get("confidence")]
        data["avg_confidence"] = round(sum(int_confidences) / len(int_confidences), 3) if int_confidences else 0

    return stats


def print_stats() -> None:
    """Imprime estadísticas de traces en consola."""
    stats = get_stats()

    print(f"\n{'=' * 50}")
    print("  TRACING STATS")
    print(f"{'=' * 50}")

    if stats["total"] == 0:
        print("  No hay traces registrados.")
        return

    print(f"\n  Total ejecuciones: {stats['total']}")
    print(f"  Bloqueadas: {stats['blocked']}")
    print(f"  Reintentos totales: {stats['total_retries']}")
    print(f"  Confidence promedio: {stats['avg_confidence']:.3f}")
    print(f"  Tiempo promedio: {stats['avg_elapsed']:.3f}s")

    print(f"\n  Por intención:")
    print(f"  {'Intención':<15} {'Count':>6} {'Avg Conf':>10}")
    print(f"  {'-'*15} {'-'*6} {'-'*10}")

    for intencion, data in sorted(stats["by_intencion"].items()):
        print(f"  {intencion:<15} {data['count']:>6} {data['avg_confidence']:>10.3f}")

    print(f"\n{'=' * 50}")
