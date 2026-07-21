"""Nodo HITL (Human-in-the-Loop): pausa el grafo para aprobacion humana.

Fase 2 (SEC-02): separa la ejecucion de la aprobacion. El nodo recibe un
action_plan estructurado, muestra un resumen al revisor, y usa interrupt()
para pausar. Solo despues de Command(resume="approve") el grafo continua
al action_executor_node. Las acciones rechazadas o con decision invalida
se marcan como rechazadas y no se ejecutan.

Multi-step: aprueba POR PASO. Cualquier paso con approval_status 'pending'
puede pausar aqui (mantiene retrocompatibilidad con tests/planes antiguos).
"""

from datetime import date, datetime, timedelta
from typing import Any

from langgraph.types import interrupt

from src.agents.action_agent import _sync_top_level_aliases, normalize_action_plan
from src.agents.state import AgentState
from src.config import get_settings


def _redact_sensitive_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Limita los argumentos mostrados al revisor para no exponer datos sensibles."""
    if tool_name == "enviar_email":
        # Mostrar solo destinatario; ocultar cuerpo y asunto del resumen HITL
        return {k: v for k, v in arguments.items() if k == "para"}

    if tool_name == "solicitar_vacaciones":
        safe = {}
        for k in ("fecha_inicio", "fecha_fin"):
            if k in arguments:
                safe[k] = arguments[k]
        # Calcular días hábiles de forma segura; si las fechas son inválidas, marcarlo.
        try:
            fi = date.fromisoformat(arguments["fecha_inicio"])
            ff = date.fromisoformat(arguments["fecha_fin"])
            safe["dias_habiles"] = _dias_habiles(fi, ff)
        except Exception:
            safe["dias_habiles"] = "inválido"
        if "motivo" in arguments:
            motivo = str(arguments["motivo"])
            safe["motivo"] = motivo if len(motivo) <= 80 else motivo[:80] + "..."
        return safe

    if tool_name == "crear_accesos":
        # Mostrar email y sistemas; created_by se inyecta por el executor.
        return {k: v for k, v in arguments.items() if k in ("email", "sistemas")}

    return {k: v for k, v in arguments.items() if k not in {"password", "token", "api_key", "secret"}}


def _dias_habiles(fi: date, ff: date) -> int:
    """Cuenta días hábiles (lun-vie) entre dos fechas inclusive."""
    total = (ff - fi).days + 1
    if total <= 0:
        return 0
    semanas = total // 7
    extra = total % 7
    habiles = semanas * 5
    inicio = fi.weekday()
    for i in range(extra):
        if (inicio + i) % 7 < 5:
            habiles += 1
    return habiles


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


def _cancel_subsequent_steps(steps: list[dict], from_index: int) -> None:
    """Cancela pasos dependientes posteriores al índice dado.

    Un paso dependiente (depends_on_previous=True) se cancela si su paso
    previo fue cancelado/rechazado. Los pasos independientes no se cancelan.
    """
    prev_cancelled = True
    for j in range(from_index + 1, len(steps)):
        if (
            prev_cancelled
            and steps[j].get("execution_status") == "not_started"
            and steps[j].get("depends_on_previous")
        ):
            steps[j]["execution_status"] = "cancelled"
        # La cancelación se propaga solo a través de pasos dependientes.
        prev_cancelled = (
            steps[j].get("execution_status") == "cancelled"
            and steps[j].get("depends_on_previous")
        )


def hitl_node(state: AgentState) -> dict:
    """Nodo del grafo: pausa para aprobacion humana basado en action_plan.

    Muestra un resumen del plan completo con el paso actual resaltado,
    espera 'approve' o 'reject', y registra quien aprobo y cuando.
    Previene ejecucion repetida.
    """
    action_plan = state.get("action_plan")

    if not action_plan:
        return {
            "requires_human_review": False,
        }

    plan = normalize_action_plan(action_plan)

    # Si el plan global ya fue rechazado/fallido, no continuar.
    if plan.get("plan_status") in ("rejected", "failed"):
        _sync_top_level_aliases(plan)
        return {
            "respuesta": plan.get("respuesta") or "⛔ Plan rechazado o fallido.",
            "action_plan": plan,
            "requires_human_review": False,
        }

    steps = plan.get("steps", [])
    current = plan.get("current_step", 0)

    # Buscar el primer paso pendiente (approval_status 'pending') desde la posición actual.
    step_index = None
    for i in range(current, len(steps)):
        if steps[i].get("approval_status") == "pending":
            step_index = i
            break

    if step_index is None:
        # No hay pasos pendientes.
        _sync_top_level_aliases(plan)
        return {
            "requires_human_review": False,
            "action_plan": plan,
        }

    step = steps[step_index]

    # Si ya fue ejecutado, no permitir cambios posteriores (replay protection)
    if step.get("execution_status") in ("succeeded", "failed") or step.get("executed_at"):
        step["approval_status"] = "rejected"
        plan["plan_status"] = "rejected"
        _cancel_subsequent_steps(steps, step_index)
        _sync_top_level_aliases(plan)
        return {
            "respuesta": "⚠️ Este paso ya fue ejecutado. No se puede aprobar de nuevo.",
            "action_plan": plan,
            "requires_human_review": False,
        }

    # Si ya fue aprobado/rechazado previamente, mantener su estado
    if step.get("approval_status") in ("approved", "rejected"):
        _sync_top_level_aliases(plan)
        return {
            "requires_human_review": False,
            "action_plan": plan,
        }

    # Si expiró, rechazar automáticamente
    if _is_action_expired(plan):
        step["approval_status"] = "expired"
        plan["plan_status"] = "rejected"
        _cancel_subsequent_steps(steps, step_index)
        _sync_top_level_aliases(plan)
        return {
            "respuesta": "⛔ La aprobación de esta acción expiró.",
            "action_plan": plan,
            "requires_human_review": False,
        }

    tool_name = step.get("tool_name", "desconocida")
    risk_level = step.get("risk_level", "unknown")
    arguments = step.get("arguments", {})
    requested_by = plan.get("requested_by", "unknown")
    role = plan.get("role", "unknown")

    safe_args = _redact_sensitive_args(tool_name, arguments)

    # Resumen con el plan completo y el paso actual resaltado.
    lines = ["=== REVISION HUMANA REQUERIDA ===", ""]
    for i, s in enumerate(steps, 1):
        marker = ">>>" if i - 1 == step_index else "   "
        status = s.get("approval_status", "unknown")
        lines.append(f"{marker} Paso {i}: {s['tool_name']} (riesgo: {s.get('risk_level', 'unknown')}) [{status}]")
    lines.extend([
        "",
        f"Paso actual: {step_index + 1} de {len(steps)}",
        f"Accion: {tool_name}",
        f"Nivel de riesgo: {risk_level.upper()}",
        f"Solicitado por: {requested_by} (rol: {role})",
        f"Argumentos (resumidos): {safe_args}",
        "",
        "Responde 'approve' para ejecutar o 'reject' para denegar.",
    ])
    resumen = "\n".join(lines)

    # Pausar ejecucion hasta que un humano responda
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
        step["approval_status"] = "rejected"
        step["approved_by"] = f"{approved_by}:invalid_decision"
        step["approved_at"] = approved_at
        plan["plan_status"] = "rejected"
        _cancel_subsequent_steps(steps, step_index)
        _sync_top_level_aliases(plan)
        return {
            "respuesta": "⛔ Decisión inválida. Debe ser 'approve' o 'reject'. Acción rechazada por seguridad.",
            "action_plan": plan,
            "approved_by": f"{approved_by}:invalid_decision",
            "approved_at": approved_at,
            "requires_human_review": False,
        }

    if decision == "approve":
        step["approval_status"] = "approved"
        step["approved_by"] = approved_by
        step["approved_at"] = approved_at
        _sync_top_level_aliases(plan)
        return {
            "action_plan": plan,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "requires_human_review": False,
        }

    # decision == "reject"
    step["approval_status"] = "rejected"
    step["approved_by"] = approved_by
    step["approved_at"] = approved_at
    plan["plan_status"] = "rejected"
    _cancel_subsequent_steps(steps, step_index)
    _sync_top_level_aliases(plan)
    return {
        "respuesta": "⛔ Acción rechazada por supervisor. Para más información, contacta al equipo de soporte.",
        "action_plan": plan,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "requires_human_review": False,
    }
