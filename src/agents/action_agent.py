"""Action Agent: nodo del grafo que planifica y ejecuta acciones.

Fase 1 (SEC-01): aplica RBAC filtrando tools por rol.
Fase 2 (SEC-02): separa planificacion de ejecucion. El planner genera un
action_plan estructurado sin ejecutar tools. Acciones de alto riesgo (email)
requieren aprobacion HITL antes de ejecutarse.

Multi-step (PLAN_MULTISTEP_ONBOARDING.md): el planner puede generar planes de
hasta `max_action_plan_steps` pasos. El executor los ejecuta secuencialmente,
pausando en HITL para cada paso high. Se mantiene retrocompatibilidad con
planes de un solo paso (antiguo formato `tool_name`/`arguments` a nivel raíz).
"""

from datetime import datetime
from typing import Any
import hashlib
import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.state import AgentState
from src.config import get_settings
from src.llm.providers import get_llm
from src.security.rbac import get_allowed_tools, validate_role
from src.tools.registry import TOOLS


class ActionStep(BaseModel):
    """Un paso dentro de un plan de acción multi-paso."""

    tool_name: str = Field(description="Nombre de la tool a ejecutar en este paso")
    arguments: dict[str, Any] = Field(description="Argumentos para la tool en formato JSON")
    reasoning: str = Field(description="Breve razonamiento de por qué se elige esta tool")
    depends_on_previous: bool = Field(
        default=False,
        description="True si este paso usa el resultado del paso anterior (placeholder {{prev_result}})",
    )


class ActionPlan(BaseModel):
    """Plan estructurado de acciones a ejecutar.

    Soporta dos modos:
    - Modo multi-paso: `steps` contiene la lista de pasos (prioritario).
    - Modo single-step (retrocompat): `tool_name`, `arguments` y `reasoning
    a nivel raíz.
    """

    tool_name: str | None = Field(
        default=None,
        description="Nombre de la tool (solo para planes de un paso/retrocompat)",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Argumentos para planes de un paso",
    )
    reasoning: str | None = Field(
        default=None,
        description="Razonamiento para planes de un paso",
    )
    steps: list[ActionStep] | None = Field(
        default=None,
        description="Lista de pasos. Tiene prioridad sobre tool_name/arguments si está presente.",
    )


SYSTEM_PROMPT_PLANNER = """Eres el planificador de acciones de Aegis Corp.
Tu trabajo es decidir qué herramienta(s) usar para la solicitud del usuario y con qué argumentos.

Herramientas disponibles para este rol:
{tools_description}

Reglas:
1. Descompón solicitudes compuestas en una lista de pasos secuenciales (máximo {max_steps}).
   Ejemplo: "crea un ticket y envía un email a rrhh@aegiscorp.com" genera 2 pasos: crear_ticket (low) y enviar_email (high).
2. Para solicitudes simples, genera un plan con un único paso.
3. Cada paso debe incluir tool_name, arguments, reasoning y depends_on_previous.
4. No inventes herramientas. Si ninguna sirve, usa tool_name="none" y arguments={{}}.
5. No ejecutes la herramienta, solo planifica.
6. Responde en español en el campo reasoning.
"""


def _tool_descriptions(tools: list) -> str:
    """Genera una descripcion de las tools disponibles para el prompt."""
    lines = []
    for tool in tools:
        name = getattr(tool, "name", str(tool))
        desc = getattr(tool, "description", "Sin descripcion")
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


def _determine_risk_level(tool_name: str) -> str:
    """Asigna nivel de riesgo segun la tool (reglas de negocio)."""
    high_risk = {"enviar_email", "solicitar_vacaciones", "crear_accesos"}
    medium_risk = {"consultar_sql"}
    if tool_name in high_risk:
        return "high"
    if tool_name in medium_risk:
        return "medium"
    return "low"


def _detect_mass_ticket_creation(raw_steps: list[dict], query: str, max_steps: int) -> bool:
    """Detecta peticiones de creación masiva de tickets en un solo paso.

    El LLM a veces colapsa "Crea 100 tickets" en un único paso con un título
    que contiene la cantidad. Se rechaza si la cantidad supera el máximo de
    pasos permitidos, ya que no es posible descomponerla de forma segura.
    """
    pattern = re.compile(r"\b(\d+)\s*tickets?\b", re.IGNORECASE)
    for match in pattern.finditer(query):
        if int(match.group(1)) > max_steps:
            return True
    for raw in raw_steps:
        if raw.get("tool_name") != "crear_ticket":
            continue
        arguments = raw.get("arguments") or {}
        for text in (arguments.get("titulo", ""), arguments.get("descripcion", ""), raw.get("reasoning", "")):
            for match in pattern.finditer(str(text)):
                if int(match.group(1)) > max_steps:
                    return True
    return False


def _new_action_id() -> str:
    """Genera un id unico para la accion (unico entre procesos)."""
    return f"act_{uuid.uuid4().hex}_{datetime.now().isoformat()}"


def _idempotency_key_for_step(action_id: str, step_index: int, tool_name: str, arguments: dict) -> str:
    """Genera una clave determinista por paso para evitar ejecuciones duplicadas."""
    canonical = json.dumps(
        {"action_id": action_id, "step_index": step_index, "tool_name": tool_name, "arguments": arguments},
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _ensure_step_runtime_fields(step: dict, action_id: str, step_index: int) -> dict:
    """Asegura que un paso tenga los campos de ejecución/risk inicializados."""
    step.setdefault("tool_name", "none")
    step["arguments"] = step.get("arguments") or {}
    step.setdefault("reasoning", "")
    step.setdefault("depends_on_previous", False)
    if step.get("risk_level") is None:
        step["risk_level"] = _determine_risk_level(step.get("tool_name", ""))
    if step.get("approval_status") is None:
        step["approval_status"] = "pending" if step["risk_level"] == "high" else "not_required"
    if step.get("execution_status") is None:
        step["execution_status"] = "not_started"
    if step.get("idempotency_key") is None:
        step["idempotency_key"] = _idempotency_key_for_step(
            action_id, step_index, step.get("tool_name", ""), step.get("arguments", {})
        )
    step.setdefault("result", None)
    step.setdefault("executed_at", None)
    step.setdefault("approved_by", None)
    step.setdefault("approved_at", None)
    step.setdefault("error", None)
    return step


def is_single_step_plan(action_plan: dict) -> bool:
    """Devuelve True si el plan usa el formato antiguo de un solo paso."""
    return bool(action_plan) and action_plan.get("tool_name") is not None and not action_plan.get("steps")


def normalize_action_plan(action_plan: dict) -> dict:
    """Normaliza un action_plan al formato multi-paso interno, mutando el dict original.

    Mantiene retrocompatibilidad con planes de un paso que tienen
    tool_name/arguments a nivel raíz.
    """
    if not action_plan:
        return None

    # Ya es multi-paso: asegurar campos runtime por paso.
    if isinstance(action_plan.get("steps"), list) and action_plan["steps"]:
        action_id = action_plan.get("action_id") or _new_action_id()
        action_plan["action_id"] = action_id
        for i, step in enumerate(action_plan["steps"]):
            _ensure_step_runtime_fields(step, action_id, i)
        action_plan.setdefault("current_step", 0)
        action_plan.setdefault("plan_status", "in_progress")
        action_plan.setdefault("executor_iterations", 0)
        return action_plan

    # Formato antiguo single-step: transformar in-place preservando el mismo objeto dict.
    action_id = action_plan.get("action_id") or _new_action_id()
    original = dict(action_plan)
    step = _ensure_step_runtime_fields(
        {
            "tool_name": original.get("tool_name"),
            "arguments": dict(original.get("arguments", {})),
            "reasoning": original.get("reasoning", ""),
            "depends_on_previous": False,
            "risk_level": original.get("risk_level"),
            "approval_status": original.get("approval_status"),
            "execution_status": original.get("execution_status"),
            "idempotency_key": original.get("idempotency_key"),
            "result": original.get("result"),
            "executed_at": original.get("executed_at"),
            "approved_by": original.get("approved_by"),
            "approved_at": original.get("approved_at"),
        },
        action_id,
        0,
    )

    action_plan.clear()
    action_plan.update({
        "action_id": action_id,
        "requested_by": original.get("requested_by", "unknown"),
        "role": original.get("role", "empleado"),
        "created_at": original.get("created_at", datetime.now().isoformat()),
        "current_step": original.get("current_step", 0),
        "plan_status": original.get("plan_status", "in_progress"),
        "executor_iterations": original.get("executor_iterations", 0),
        "steps": [step],
    })
    # Preservar campos legacy a nivel raíz para compatibilidad con tests/traazas antiguas.
    for key in (
        "tool_name", "arguments", "reasoning", "risk_level", "approval_status",
        "execution_status", "idempotency_key", "result", "executed_at",
        "approved_by", "approved_at", "respuesta", "fuentes",
    ):
        if key in original:
            action_plan[key] = original[key]
    # Sincronizar alias a nivel raíz con el paso actual
    if action_plan.get("current_step", 0) < len(action_plan["steps"]):
        current_step = action_plan["steps"][action_plan["current_step"]]
        for key in (
            "tool_name", "arguments", "reasoning", "risk_level", "approval_status",
            "execution_status", "idempotency_key", "result", "executed_at",
            "approved_by", "approved_at",
        ):
            action_plan[key] = current_step.get(key)
    return action_plan


def _sync_top_level_aliases(plan: dict) -> dict:
    """Sincroniza alias a nivel raíz con el paso actual (para retrocompatibilidad)."""
    steps = plan.get("steps", [])
    current = plan.get("current_step", 0)
    if not steps:
        return plan
    if current >= len(steps):
        current = len(steps) - 1
    step = steps[current]
    plan["tool_name"] = step.get("tool_name")
    plan["arguments"] = step.get("arguments")
    plan["reasoning"] = step.get("reasoning")
    plan["risk_level"] = step.get("risk_level")
    plan["approval_status"] = step.get("approval_status")
    plan["execution_status"] = step.get("execution_status")
    plan["idempotency_key"] = step.get("idempotency_key")
    plan["result"] = step.get("result")
    plan["executed_at"] = step.get("executed_at")
    plan["approved_by"] = step.get("approved_by")
    plan["approved_at"] = step.get("approved_at")
    return plan


def _raw_step_to_dict(raw: Any) -> dict:
    """Convierte un paso del LLM (ActionStep o dict) a dict manejable."""
    if isinstance(raw, dict):
        return dict(raw)
    return {
        "tool_name": getattr(raw, "tool_name", None),
        "arguments": getattr(raw, "arguments", {}) or {},
        "reasoning": getattr(raw, "reasoning", "") or "",
        "depends_on_previous": getattr(raw, "depends_on_previous", False),
    }


def _inject_prev_result(arguments: dict, step: dict, previous_steps: list[dict]) -> dict:
    """Sustituye el placeholder {{prev_result}} por el resultado del paso previo."""
    if not step.get("depends_on_previous"):
        return dict(arguments)

    idx = previous_steps.index(step)
    prev_result = ""
    for i in range(idx - 1, -1, -1):
        if previous_steps[i].get("execution_status") == "succeeded":
            prev_result = previous_steps[i].get("result") or ""
            break

    def _replace(obj: Any) -> Any:
        if isinstance(obj, str):
            return obj.replace("{{prev_result}}", str(prev_result))
        if isinstance(obj, dict):
            return {k: _replace(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_replace(v) for v in obj]
        return obj

    return _replace(dict(arguments))


def _inject_ownership(arguments: dict, step: dict, state: AgentState) -> dict:
    """Inyecta ownership y auditoría real en los argumentos de un paso."""
    arguments = dict(arguments)
    tool_name = step.get("tool_name", "")
    user_id = state.get("user_id", "unknown")
    role = state.get("role", "empleado")

    OWNERSHIP_TOOLS = {
        "crear_ticket",
        "listar_tickets",
        "buscar_ticket",
        "consultar_saldo_vacaciones",
        "solicitar_vacaciones",
        "listar_solicitudes_vacaciones",
        "crear_accesos",
    }
    if tool_name not in OWNERSHIP_TOOLS:
        return arguments

    arguments["role"] = role
    if tool_name in ("crear_ticket", "solicitar_vacaciones", "crear_accesos") or role != "admin":
        arguments["created_by"] = user_id
    elif not arguments.get("created_by"):
        arguments["created_by"] = user_id

    if tool_name == "solicitar_vacaciones":
        arguments["idempotency_key"] = step.get("idempotency_key", "")
        arguments["aprobado_por"] = step.get("approved_by") or ""

    return arguments


def _finalize_plan(plan: dict, error_message: str | None = None) -> dict:
    """Construye la respuesta final de un plan multi-paso y sincroniza alias."""
    steps = plan.get("steps", [])
    status = plan.get("plan_status", "in_progress")
    parts: list[str] = []

    if error_message:
        parts.append(error_message)

    if status == "completed":
        if len(steps) == 1:
            parts.append(steps[0].get("result") or "Acción completada.")
        else:
            lines = ["Plan completado:"]
            for i, s in enumerate(steps, 1):
                lines.append(f"  Paso {i} ({s['tool_name']}): {s.get('result', 'completado')}")
            parts.append("\n".join(lines))
    elif status == "failed":
        executed = [s for s in steps if s.get("execution_status") == "succeeded"]
        cancelled = [s for s in steps if s.get("execution_status") == "cancelled"]
        lines = ["El plan falló."]
        if executed:
            lines.append("Ejecutados:")
            for s in executed:
                lines.append(f"  - {s['tool_name']}: {s.get('result', 'ok')}")
        if cancelled:
            lines.append("Cancelados:")
            for s in cancelled:
                lines.append(f"  - {s['tool_name']}")
        parts.append("\n".join(lines))
    elif status == "rejected":
        parts.append("⛔ Plan rechazado por supervisor.")
    else:
        parts.append(plan.get("respuesta") or "Plan en estado desconocido.")

    respuesta = "\n\n".join([p for p in parts if p])
    plan["respuesta"] = respuesta
    _sync_top_level_aliases(plan)

    return {
        "respuesta": respuesta,
        "fuentes": [{"source": f"tool:{s['tool_name']}"} for s in steps if s.get("execution_status") == "succeeded"],
        "action_plan": plan,
    }


def action_planner_node(state: AgentState) -> dict:
    """Nodo del grafo: planifica una acción (multi-paso o simple).

    Valida RBAC, obtiene tools permitidas, y usa structured output
    para generar un action_plan estructurado.
    """
    role = state.get("role")
    query = state["query"]

    # Fail closed: sin rol explicito, no hay acceso a tools
    if not validate_role(role):
        return {
            "respuesta": "⛔ Rol inválido o no especificado. Contacta al administrador.",
            "fuentes": [],
            "tool_name": None,
            "authorization_decision": "unknown_role",
            "confidence": 1.0,
            "action_plan": None,
        }

    # Guarda explícita: no re-planificar un plan que ya está en progreso.
    existing_plan = state.get("action_plan")
    if existing_plan:
        normalized = normalize_action_plan(existing_plan)
        if normalized.get("plan_status") == "in_progress" and normalized.get("current_step", 0) < len(normalized.get("steps", [])):
            _sync_top_level_aliases(normalized)
            return {
                "fuentes": [],
                "tool_name": normalized["steps"][0].get("tool_name") if normalized.get("steps") else None,
                "authorization_decision": "allowed",
                "action_plan": normalized,
            }

    allowed_tools = get_allowed_tools(role)
    if not allowed_tools:
        return {
            "respuesta": "⛔ No tienes permisos para ejecutar acciones.",
            "fuentes": [],
            "tool_name": None,
            "authorization_decision": "denied",
            "confidence": 1.0,
            "action_plan": None,
        }

    # Preparar prompt con tools permitidas
    settings = get_settings()
    max_steps = settings.max_action_plan_steps
    tools_description = _tool_descriptions(allowed_tools)
    prompt = SYSTEM_PROMPT_PLANNER.format(tools_description=tools_description, max_steps=max_steps)

    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(ActionPlan, method="function_calling")

    plan = structured_llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=query),
    ])

    # Normalizar a lista de pasos
    if plan.steps and len(plan.steps) > 0:
        raw_steps = [_raw_step_to_dict(s) for s in plan.steps]
    elif plan.tool_name:
        raw_steps = [_raw_step_to_dict({
            "tool_name": plan.tool_name,
            "arguments": plan.arguments or {},
            "reasoning": plan.reasoning or "",
            "depends_on_previous": False,
        })]
    else:
        reasoning = plan.reasoning or "No se encontró una herramienta adecuada para tu solicitud."
        return {
            "respuesta": f"No puedo realizar esta acción: {reasoning}",
            "fuentes": [],
            "tool_name": None,
            "authorization_decision": "denied",
            "confidence": 1.0,
            "action_plan": None,
        }

    # Límite duro de pasos (fail closed)
    if len(raw_steps) > max_steps:
        return {
            "respuesta": f"⛔ El plan excede el límite de {max_steps} pasos. Descompón la solicitud.",
            "fuentes": [],
            "tool_name": None,
            "authorization_decision": "denied",
            "confidence": 1.0,
            "action_plan": None,
        }

    # Rechazo determinista de creación masiva de tickets.
    if _detect_mass_ticket_creation(raw_steps, query, max_steps):
        return {
            "respuesta": "⛔ No puedo procesar solicitudes de creación masiva de tickets. Descompón la solicitud en pasos individuales.",
            "fuentes": [],
            "tool_name": None,
            "authorization_decision": "denied",
            "confidence": 1.0,
            "action_plan": None,
        }

    action_id = _new_action_id()
    steps = []
    allowed_names = {getattr(t, "name", None) for t in allowed_tools if getattr(t, "name", None)}

    for i, raw in enumerate(raw_steps):
        tool_name = (raw.get("tool_name") or "").strip().lower()

        if tool_name == "none":
            return {
                "respuesta": f"No puedo realizar esta acción: {raw.get('reasoning') or 'No hay herramienta adecuada.'}",
                "fuentes": [],
                "tool_name": None,
                "authorization_decision": "denied",
                "confidence": 1.0,
                "action_plan": None,
            }

        if tool_name not in TOOLS:
            return {
                "respuesta": f"⛔ Herramienta '{tool_name}' no existe o no está disponible.",
                "fuentes": [],
                "tool_name": tool_name,
                "authorization_decision": "denied",
                "confidence": 1.0,
                "action_plan": None,
            }

        if tool_name not in allowed_names:
            return {
                "respuesta": f"No puedo: no tienes permiso para usar la herramienta '{tool_name}'.",
                "fuentes": [],
                "tool_name": tool_name,
                "authorization_decision": "denied",
                "confidence": 1.0,
                "action_plan": None,
            }

        # Validación determinista fail-closed para solicitudes de vacaciones.
        if tool_name == "solicitar_vacaciones":
            from src.tools.vacaciones import _validar_solicitud_vacaciones
            validation_error = _validar_solicitud_vacaciones(raw.get("arguments") or {})
            if validation_error:
                return {
                    "respuesta": f"No puedo procesar la solicitud. {validation_error}",
                    "fuentes": [],
                    "tool_name": tool_name,
                    "authorization_decision": "denied",
                    "confidence": 1.0,
                    "action_plan": None,
                }

        risk_level = _determine_risk_level(tool_name)
        approval_status = "pending" if risk_level == "high" else "not_required"

        step = {
            "tool_name": tool_name,
            "arguments": dict(raw.get("arguments") or {}),
            "reasoning": raw.get("reasoning", ""),
            "depends_on_previous": bool(raw.get("depends_on_previous", False)),
            "risk_level": risk_level,
            "approval_status": approval_status,
            "execution_status": "not_started",
            "idempotency_key": _idempotency_key_for_step(action_id, i, tool_name, raw.get("arguments") or {}),
            "result": None,
            "executed_at": None,
            "approved_by": None,
            "approved_at": None,
            "error": None,
        }
        steps.append(step)

    action_plan = {
        "action_id": action_id,
        "requested_by": state.get("user_id", "unknown"),
        "role": role,
        "created_at": datetime.now().isoformat(),
        "current_step": 0,
        "plan_status": "in_progress",
        "executor_iterations": 0,
        "steps": steps,
    }

    # Alias a nivel raíz para retrocompatibilidad (apuntan al primer paso).
    if steps:
        _sync_top_level_aliases(action_plan)

    return {
        "fuentes": [],
        "tool_name": action_plan.get("tool_name"),
        "authorization_decision": "allowed",
        "action_plan": action_plan,
    }


def _execute_single_step(step: dict, steps: list[dict], state: AgentState) -> tuple[bool, str | None]:
    """Ejecuta un paso individual y devuelve (éxito, mensaje_error).

    Modifica `step` in-place con result/executed_at/execution_status.
    """
    arguments = _inject_prev_result(step.get("arguments", {}), step, steps)
    arguments = _inject_ownership(arguments, step, state)

    role = state.get("role", "empleado")
    allowed_tools = get_allowed_tools(role)
    allowed_names = {getattr(t, "name", None) for t in allowed_tools if getattr(t, "name", None)}
    tool_name = step.get("tool_name", "")
    if tool_name not in allowed_names or tool_name not in TOOLS:
        return False, f"⛔ No tienes permiso para ejecutar '{tool_name}'."

    tool = TOOLS[tool_name]

    try:
        result = tool.invoke(arguments) if hasattr(tool, "invoke") else tool(**arguments)
    except Exception as e:
        msg = str(e)
        if not msg.startswith("Error:"):
            msg = f"Error al ejecutar '{tool_name}': {e}"
        return False, msg

    step["execution_status"] = "succeeded"
    step["result"] = result
    step["executed_at"] = datetime.now().isoformat()
    return True, None


def action_executor_node(state: AgentState) -> dict:
    """Nodo del grafo: ejecuta el plan de acciones aprobado paso a paso.

    - Ejecuta todos los pasos consecutivos aprobados/no requeridos en una sola invocación.
    - Pausa ante pasos pendientes (deja que el router envíe a HITL).
    - Cancela pasos posteriores si un paso falla.
    - No re-ejecuta pasos ya completados.
    """
    action_plan = state.get("action_plan")

    if not action_plan:
        return {
            "respuesta": "No hay ninguna acción pendiente para ejecutar.",
            "fuentes": [],
        }

    plan = normalize_action_plan(action_plan)
    status = plan.get("plan_status")

    if status in ("rejected", "failed"):
        return _finalize_plan(plan)

    if status == "completed":
        return _finalize_plan(plan)

    steps = plan.get("steps", [])
    if not steps:
        return {
            "respuesta": "El plan de acciones está vacío.",
            "fuentes": [],
            "action_plan": plan,
        }

    # Guarda anti-loop: contador de iteraciones del executor.
    settings = get_settings()
    max_steps = settings.max_action_plan_steps
    # El contador puede venir en el state para compatibilidad con tests de routing.
    plan["executor_iterations"] = max(plan.get("executor_iterations", 0), state.get("executor_iterations", 0)) + 1
    if plan["executor_iterations"] > max_steps + 1:
        plan["plan_status"] = "failed"
        current = plan.get("current_step", 0)
        for s in steps[current:]:
            if s.get("execution_status") == "not_started":
                s["execution_status"] = "cancelled"
        _sync_top_level_aliases(plan)
        return _finalize_plan(plan, "Plan cancelado por exceder el límite de iteraciones.")

    current = plan.get("current_step", 0)

    while True:
        # Saltar pasos ya ejecutados (replay protection)
        while current < len(steps) and steps[current].get("execution_status") == "succeeded":
            current += 1
        plan["current_step"] = current

        if current >= len(steps):
            plan["plan_status"] = "completed"
            _sync_top_level_aliases(plan)
            return _finalize_plan(plan)

        step = steps[current]

        # Si el paso actual está pendiente, no ejecutar; el router lo envía a HITL.
        if step.get("approval_status") == "pending":
            _sync_top_level_aliases(plan)
            return {
                "respuesta": "⛔ Esta acción no ha sido aprobada.",
                "fuentes": [],
                "action_plan": plan,
            }

        # Si no está aprobado (y no es pendiente), no ejecutar.
        if step.get("approval_status") not in ("approved", "not_required"):
            _sync_top_level_aliases(plan)
            return {
                "respuesta": "⛔ Esta acción no ha sido aprobada.",
                "fuentes": [],
                "action_plan": plan,
            }

        # Ejecutar el paso actual
        success, error = _execute_single_step(step, steps, state)
        if not success:
            step["execution_status"] = "failed"
            step["error"] = error
            step["executed_at"] = datetime.now().isoformat()
            plan["plan_status"] = "failed"
            for s in steps[current + 1 :]:
                if s.get("execution_status") == "not_started":
                    s["execution_status"] = "cancelled"
            _sync_top_level_aliases(plan)
            return _finalize_plan(plan, error)

        # Avanzar al siguiente paso y continuar el loop
        current += 1
        plan["current_step"] = current

        if current >= len(steps):
            plan["plan_status"] = "completed"
            _sync_top_level_aliases(plan)
            return _finalize_plan(plan)
