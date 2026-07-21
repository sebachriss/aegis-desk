"""Action Agent: nodo del grafo que planifica y ejecuta acciones.

Fase 1 (SEC-01): aplica RBAC filtrando tools por rol.
Fase 2 (SEC-02): separa planificacion de ejecucion. El planner genera un
action_plan estructurado sin ejecutar tools. Acciones de alto riesgo (email)
requieren aprobacion HITL antes de ejecutarse.
"""

from datetime import datetime
from typing import Any
import hashlib
import json
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.state import AgentState
from src.llm.providers import get_llm
from src.security.rbac import get_allowed_tools, validate_role
from src.tools.registry import TOOLS


class ActionPlan(BaseModel):
    """Plan estructurado de una accion a ejecutar."""

    tool_name: str = Field(description="Nombre de la tool a ejecutar")
    arguments: dict[str, Any] = Field(description="Argumentos para la tool en formato JSON")
    reasoning: str = Field(description="Breve razonamiento de por que se elige esta tool")


SYSTEM_PROMPT_PLANNER = """Eres el planificador de acciones de Aegis Corp.
Tu trabajo es decidir qué herramienta usar para la solicitud del usuario y con qué argumentos.

Herramientas disponibles para este rol:
{tools_description}

Reglas:
1. Elige UNA sola herramienta de la lista.
2. Devuelve los argumentos exactos que requiere la herramienta.
3. No inventes herramientas. Si ninguna sirve, usa tool_name="none" y arguments={{}}, y reasoning explica por qué.
4. No ejecutes la herramienta, solo planifica.
5. Responde en español en el campo reasoning.
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
    high_risk = {"enviar_email", "solicitar_vacaciones"}
    medium_risk = {"consultar_sql"}
    if tool_name in high_risk:
        return "high"
    if tool_name in medium_risk:
        return "medium"
    return "low"


def _new_action_id() -> str:
    """Genera un id unico para la accion (unico entre procesos)."""
    return f"act_{uuid.uuid4().hex}_{datetime.now().isoformat()}"


def _idempotency_key(tool_name: str, arguments: dict) -> str:
    """Genera una clave determinista para evitar ejecuciones duplicadas."""
    canonical = json.dumps({"tool_name": tool_name, "arguments": arguments}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def action_planner_node(state: AgentState) -> dict:
    """Nodo del grafo: planifica una accion sin ejecutarla.

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
    tools_description = _tool_descriptions(allowed_tools)
    prompt = SYSTEM_PROMPT_PLANNER.format(tools_description=tools_description)

    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(ActionPlan, method="function_calling")

    plan = structured_llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=query),
    ])

    # Normalizar: validar que la tool exista y este permitida
    tool_name = plan.tool_name.strip().lower() if plan.tool_name else "none"
    if tool_name == "none":
        reasoning = plan.reasoning or "No se encontró una herramienta adecuada para tu solicitud."
        return {
            "respuesta": f"No puedo realizar esta acción: {reasoning}",
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

    allowed_names = {getattr(t, "name", None) for t in allowed_tools if getattr(t, "name", None)}
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
    # Si las fechas/motivo no pasan, rechazamos antes de HITL.
    if tool_name == "solicitar_vacaciones":
        from src.tools.vacaciones import _validar_solicitud_vacaciones
        validation_error = _validar_solicitud_vacaciones(plan.arguments)
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

    action_plan = {
        "action_id": _new_action_id(),
        "tool_name": tool_name,
        "arguments": plan.arguments,
        "requested_by": state.get("user_id", "unknown"),
        "role": role,
        "risk_level": risk_level,
        "approval_status": approval_status,
        "execution_status": "not_started",
        "idempotency_key": _idempotency_key(tool_name, plan.arguments),
        "created_at": datetime.now().isoformat(),
        "executed_at": None,
        "reasoning": plan.reasoning,
    }

    return {
        "fuentes": [],
        "tool_name": tool_name,
        "authorization_decision": "allowed",
        "action_plan": action_plan,
    }


def action_executor_node(state: AgentState) -> dict:
    """Nodo del grafo: ejecuta la tool del action_plan aprobado.

    Valida que la accion este aprobada (o no requiera aprobacion),
    ejecuta la tool idempotente, y devuelve la respuesta.
    """
    action_plan = state.get("action_plan")

    if not action_plan:
        return {
            "respuesta": "No hay ninguna acción pendiente para ejecutar.",
            "fuentes": [],
        }

    approval_status = action_plan.get("approval_status")
    if approval_status not in ("approved", "not_required"):
        return {
            "respuesta": "⛔ Esta acción no ha sido aprobada.",
            "fuentes": [],
        }

    if action_plan.get("execution_status") == "succeeded":
        return {
            "respuesta": action_plan.get("result", "Esta acción ya fue ejecutada."),
            "fuentes": [],
            "action_plan": action_plan,
        }

    tool_name = action_plan.get("tool_name")
    if not tool_name or tool_name not in TOOLS:
        return {
            "respuesta": f"⛔ Herramienta '{tool_name}' no disponible.",
            "fuentes": [],
        }

    role = state.get("role", "empleado")
    allowed_tools = get_allowed_tools(role)
    allowed_names = {getattr(t, "name", None) for t in allowed_tools if getattr(t, "name", None)}
    if tool_name not in allowed_names:
        return {
            "respuesta": f"⛔ No tienes permiso para ejecutar '{tool_name}'.",
            "fuentes": [],
        }

    tool = TOOLS[tool_name]
    arguments = action_plan.get("arguments", {})

    # Inyectar ownership/auditoria para tickets y vacaciones
    OWNERSHIP_TOOLS = {
        "crear_ticket",
        "listar_tickets",
        "buscar_ticket",
        "consultar_saldo_vacaciones",
        "solicitar_vacaciones",
        "listar_solicitudes_vacaciones",
    }
    if tool_name in OWNERSHIP_TOOLS:
        arguments = dict(arguments)
        user_id = state.get("user_id", "unknown")
        role = state.get("role", "empleado")
        arguments["role"] = role
        # Para crear/solicitar, siempre inyectar created_by real (evita suplantación).
        # Para consultar/listar/buscar, el admin puede especificar un target; el resto no.
        if tool_name in ("crear_ticket", "solicitar_vacaciones") or role != "admin":
            arguments["created_by"] = user_id
        elif not arguments.get("created_by"):
            arguments["created_by"] = user_id

        # Datos de auditoría para solicitudes de vacaciones (post-HITL)
        if tool_name == "solicitar_vacaciones":
            arguments["idempotency_key"] = action_plan.get("idempotency_key", "")
            arguments["aprobado_por"] = action_plan.get("approved_by") or ""

    try:
        result = tool.invoke(arguments) if hasattr(tool, "invoke") else tool(**arguments)
        action_plan["execution_status"] = "succeeded"
        action_plan["executed_at"] = datetime.now().isoformat()
        action_plan["result"] = result

        return {
            "respuesta": result,
            "fuentes": [{"source": f"tool:{tool_name}"}],
            "action_plan": action_plan,
        }
    except Exception as e:
        action_plan["execution_status"] = "failed"
        action_plan["error"] = str(e)
        msg = str(e)
        # Si la tool levantó un ValueError con mensaje de negocio, mostrarlo limpio.
        if not msg.startswith("Error:"):
            msg = f"Error al ejecutar '{tool_name}': {e}"
        return {
            "respuesta": msg,
            "fuentes": [],
            "action_plan": action_plan,
        }


# Nota: el grafo debe usar action_planner_node/action_executor_node, no action_node.
