"""Nodo HITL (Human-in-the-Loop): pausa el grafo para aprobacion humana.

Fase 2 (SEC-02): separa la ejecucion de la aprobacion. El nodo recibe un
action_plan estructurado, muestra un resumen al revisor, y usa interrupt()
para pausar. Solo despues de Command(resume="approve") el grafo continua
al action_executor_node. Las acciones rechazadas o con decision invalida
se marcan como rechazadas y no se ejecutan.
"""

from datetime import datetime

from langgraph.types import interrupt

from src.agents.state import AgentState


def _redact_sensitive_args(tool_name: str, arguments: dict) -> dict:
    """Limita los argumentos mostrados al revisor para no exponer datos sensibles."""
    if tool_name == "enviar_email":
        return {k: v for k, v in arguments.items() if k not in ("cuerpo", "asunto") or k == "para"}
    return {k: v for k, v in arguments.items() if k not in ("password", "token", "api_key")}


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

    # Si ya fue aprobada o rechazada, no volver a pausar
    current_status = action_plan.get("approval_status")
    if current_status in ("approved", "rejected"):
        return {
            "requires_human_review": False,
        }

    # Si ya fue ejecutada, no aprobar de nuevo
    if action_plan.get("execution_status") == "succeeded" or action_plan.get("executed_at"):
        return {
            "respuesta": "⚠️ Esta acción ya fue ejecutada. No se puede aprobar de nuevo.",
            "action_plan": {**action_plan, "approval_status": "rejected"},
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
    decision = interrupt(resumen)

    # Validar decision estrictamente
    if decision not in ("approve", "reject"):
        return {
            "respuesta": "⛔ Decisión inválida. Debe ser 'approve' o 'reject'. Acción rechazada por seguridad.",
            "action_plan": {**action_plan, "approval_status": "rejected"},
            "requires_human_review": False,
        }

    approved_by = state.get("user_id", "unknown")
    approved_at = datetime.now().isoformat()

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
