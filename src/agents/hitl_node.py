"""Nodo HITL (Human-in-the-Loop): pausa el grafo para aprobacion humana.

Fase 2 (SEC-02): separa la ejecucion de la aprobacion. El nodo recibe un
action_plan estructurado, muestra un resumen al revisor, y usa interrupt()
para pausar. Solo despues de Command(resume="approve") el grafo continua
al action_executor_node. Las acciones rechazadas o con decision invalida
se marcan como rechazadas y no se ejecutan.
"""

from datetime import datetime, timedelta
from typing import Any

from langgraph.types import interrupt

from src.agents.state import AgentState
from src.config import get_settings


def _redact_sensitive_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Limita los argumentos mostrados al revisor para no exponer datos sensibles."""
    if tool_name == "enviar_email":
        # Mostrar solo destinatario; ocultar cuerpo y asunto del resumen HITL
        return {k: v for k, v in arguments.items() if k == "para"}
    return {k: v for k, v in arguments.items() if k not in {"password", "token", "api_key", "secret"}}


def _is_action_expired(action_plan: dict) -> bool:
    """Devuelve True si la acción expiró según la configuración del HITL."""
    created_at = action_plan.get("created_at")
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return False
    settings = get_settings()
    expires = created + timedelta(seconds=settings.hitl_expiration_seconds)
    return datetime.now() > expires


def hitl_node(state: AgentState) -> dict:
    """Nodo del grafo: pausa para aprobacion humana basado en action_plan.

    Muestra un resumen estructurado, espera 'approve' o 'reject',
    y registra quien aprobo y cuando. Previene ejecucion repetida.
    """
    action_plan = state.get("action_plan")

    if not action_plan:
        return {
            "respuesta": "No se requiere revision humana.",
            "requires_human_review": False,
        }

    # Si ya fue ejecutada, no permitir cambios posteriores (replay protection)
    if action_plan.get("execution_status") in ("succeeded", "failed") or action_plan.get("executed_at"):
        return {
            "respuesta": "⚠️ Esta acción ya fue ejecutada. No se puede aprobar de nuevo.",
            "action_plan": {**action_plan, "approval_status": "rejected"},
            "requires_human_review": False,
        }

    # Si ya fue aprobada/rechazada previamente, mantener su estado
    current_status = action_plan.get("approval_status")
    if current_status in ("approved", "rejected"):
        return {
            "requires_human_review": False,
        }

    # Si expiró, rechazar automáticamente
    if _is_action_expired(action_plan):
        updated_plan = {**action_plan, "approval_status": "expired"}
        return {
            "respuesta": "⛔ La aprobación de esta acción expiró.",
            "action_plan": updated_plan,
            "requires_human_review": False,
        }

    tool_name = action_plan.get("tool_name", "desconocida")
    risk_level = action_plan.get("risk_level", "unknown")
    arguments = action_plan.get("arguments", {})
    requested_by = action_plan.get("requested_by", "unknown")
    role = action_plan.get("role", "unknown")

    safe_args = _redact_sensitive_args(tool_name, arguments)

    resumen = f"""=== REVISION HUMANA REQUERIDA ===

Accion: {tool_name}
Nivel de riesgo: {risk_level.upper()}
Solicitado por: {requested_by} (rol: {role})
Argumentos (resumidos): {safe_args}

Responde 'approve' para ejecutar o 'reject' para denegar.
"""

    # Pausar ejecucion hasta que un humano responda
    # El backend puede reanudar con un string o con un dict que incluya
    # la decision y el usuario aprobador real (para auditoria correcta).
    resume_value = interrupt(resumen)

    if isinstance(resume_value, dict):
        decision = resume_value.get("decision", "").lower()
        approved_by = resume_value.get("approved_by") or state.get("user_id", "unknown")
    else:
        decision = (resume_value or "").lower()
        approved_by = state.get("user_id", "unknown")

    approved_at = datetime.now().isoformat()

    # Decision invalida: bloquear por seguridad y registrar quien intento
    if decision not in ("approve", "reject"):
        updated_plan = {
            **action_plan,
            "approval_status": "rejected",
            "approved_by": f"{approved_by}:invalid_decision",
            "approved_at": approved_at,
        }
        return {
            "respuesta": "⛔ Decisión inválida. Debe ser 'approve' o 'reject'. Acción rechazada por seguridad.",
            "action_plan": updated_plan,
            "approved_by": f"{approved_by}:invalid_decision",
            "approved_at": approved_at,
            "requires_human_review": False,
        }

    if decision == "approve":
        updated_plan = {
            **action_plan,
            "approval_status": "approved",
            "approved_by": approved_by,
            "approved_at": approved_at,
        }
        return {
            "action_plan": updated_plan,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "requires_human_review": False,
        }

    # decision == "reject"
    updated_plan = {
        **action_plan,
        "approval_status": "rejected",
        "approved_by": approved_by,
        "approved_at": approved_at,
    }
    return {
        "respuesta": "⛔ Acción rechazada por supervisor. Para más información, contacta al equipo de soporte.",
        "action_plan": updated_plan,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "requires_human_review": False,
    }
