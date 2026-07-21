"""Onboarding Agent: worker para consultas de onboarding y alta de empleados.

- Consulta: responde usando RAG sobre onboarding.md.
- Alta: genera un MultiActionPlan determinista de 3 pasos:
  1. crear_ticket para IT (low)
  2. crear_accesos (high, HITL)
  3. enviar_email de bienvenida (high, HITL)

Solo los administradores pueden iniciar el alta de un empleado.
"""

from datetime import datetime

import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.action_agent import _idempotency_key_for_step, _sync_top_level_aliases
from src.agents.state import AgentState
from src.llm.providers import get_fast_llm
from src.rag.chain import rag_query


# Patrones adicionales para detectar alta de empleado
ALTA_PATTERNS = [
    r"\b(dar de alta|alta de empleado|alta empleado|nuevo empleado|empleado nuevo|contratar a|incorporar a|ingresar a)\b",
]


class OnboardingParams(BaseModel):
    """Parámetros extraídos de una solicitud de onboarding."""

    es_alta: bool = Field(description="True si el usuario quiere iniciar el alta de un empleado")
    nombre: str | None = Field(default=None, description="Nombre del nuevo empleado")
    email: str | None = Field(default=None, description="Email del nuevo empleado")
    departamento: str | None = Field(default=None, description="Departamento del nuevo empleado")


SYSTEM_PROMPT = """Eres el agente de onboarding de Aegis Corp.

Tu trabajo:
- Si el usuario pregunta sobre el proceso de onboarding (bienvenida, día 1, equipos, cuentas, buddy, accesos, VPN, formación), responde con la información documentada.
- Si el usuario pide dar de alta a un nuevo empleado, extrae nombre, email y departamento. El email debe ser corporativo (@aegiscorp.com o @aegis.com).
- No inventes datos. Si falta información crítica, indica qué falta en el campo apropiado.
- Si la frase no es ni consulta ni alta, es_alta = false.
"""


def _extract_email(query: str) -> str | None:
    """Extrae el primer email del texto."""
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", query)
    return match.group(0) if match else None


def onboarding_node(state: AgentState) -> dict:
    """Nodo del grafo: atiende consultas de onboarding o genera plan de alta.

    - Consulta: usa RAG y devuelve fuentes.
    - Alta: genera un action_plan determinista de 3 pasos.
    """
    query = state["query"]
    role = state.get("role", "empleado")

    # Usar el LLM rápido para extraer parámetros e intención.
    llm = get_fast_llm(temperature=0)
    structured = llm.with_structured_output(OnboardingParams)
    try:
        params = structured.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=query),
        ])
    except Exception:
        params = OnboardingParams(es_alta=False, nombre=None, email=None, departamento=None)

    is_alta = params.es_alta or any(re.search(p, query, re.IGNORECASE) for p in ALTA_PATTERNS)

    if is_alta:
        if role != "admin":
            return {
                "respuesta": "⛔ Solo los administradores pueden iniciar el alta de un empleado.",
                "fuentes": [],
                "intencion": "onboarding",
                "confidence": 1.0,
                "authorization_decision": "denied",
            }

        email = (params.email or "").strip() or _extract_email(query) or ""
        if not email or "@" not in email:
            return {
                "respuesta": "⛔ No pude identificar un email válido para el nuevo empleado.",
                "fuentes": [],
                "intencion": "onboarding",
                "confidence": 1.0,
            }

        domain = email.split("@")[-1].lower()
        if domain not in {"aegiscorp.com", "aegis.com"}:
            return {
                "respuesta": f"⛔ El email '{email}' no pertenece al dominio corporativo.",
                "fuentes": [],
                "intencion": "onboarding",
                "confidence": 1.0,
            }

        nombre = (params.nombre or "").strip() or "Nuevo empleado"
        departamento = (params.departamento or "").strip() or "Por definir"

        # Extraer nombre si viene después de "dar de alta a"
        if nombre == "Nuevo empleado":
            match = re.search(r"(?:dar de alta|alta de empleado|nuevo empleado|empleado nuevo|contratar a|incorporar a)\s+(?:a\s+)?([^\(\)@]+?)(?:\s*\(|\s+en\s+|\s+con\s+email|\s*,|\s*$)", query, re.IGNORECASE)
            if match:
                nombre = match.group(1).strip()

        user_id = state.get("user_id", "unknown")
        action_id = f"act_{uuid.uuid4().hex}_{datetime.now().isoformat()}"

        steps = [
            {
                "tool_name": "crear_ticket",
                "arguments": {
                    "titulo": f"Alta de empleado: {nombre}",
                    "descripcion": f"Solicitud de alta para {nombre} ({email}), departamento: {departamento}.",
                    "prioridad": "media",
                },
                "reasoning": "Solicitar equipo y cuenta de dominio al equipo de IT",
                "depends_on_previous": False,
                "risk_level": "low",
                "approval_status": "not_required",
                "execution_status": "not_started",
                "idempotency_key": _idempotency_key_for_step(
                    action_id, 0, "crear_ticket",
                    {"titulo": f"Alta de empleado: {nombre}", "descripcion": email, "prioridad": "media"},
                ),
                "result": None,
                "executed_at": None,
                "approved_by": None,
                "approved_at": None,
                "error": None,
            },
            {
                "tool_name": "crear_accesos",
                "arguments": {
                    "email": email,
                    "sistemas": ["email", "vpn", "slack", "github", "erp"],
                },
                "reasoning": "Crear accesos a sistemas corporativos",
                "depends_on_previous": False,
                "risk_level": "high",
                "approval_status": "pending",
                "execution_status": "not_started",
                "idempotency_key": _idempotency_key_for_step(
                    action_id, 1, "crear_accesos", {"email": email, "sistemas": ["email", "vpn", "slack", "github", "erp"]},
                ),
                "result": None,
                "executed_at": None,
                "approved_by": None,
                "approved_at": None,
                "error": None,
            },
            {
                "tool_name": "enviar_email",
                "arguments": {
                    "para": email,
                    "asunto": "Bienvenida a Aegis Corp",
                    "cuerpo": f"Hola {nombre},\n\nBienvenido a Aegis Corp. Tu departamento es {departamento}.",
                },
                "reasoning": "Enviar email de bienvenida al nuevo empleado",
                "depends_on_previous": False,
                "risk_level": "high",
                "approval_status": "pending",
                "execution_status": "not_started",
                "idempotency_key": _idempotency_key_for_step(
                    action_id, 2, "enviar_email",
                    {"para": email, "asunto": "Bienvenida", "cuerpo": "..."},
                ),
                "result": None,
                "executed_at": None,
                "approved_by": None,
                "approved_at": None,
                "error": None,
            },
        ]

        action_plan = {
            "action_id": action_id,
            "requested_by": user_id,
            "role": role,
            "created_at": datetime.now().isoformat(),
            "current_step": 0,
            "plan_status": "in_progress",
            "executor_iterations": 0,
            "steps": steps,
        }
        _sync_top_level_aliases(action_plan)

        return {
            "action_plan": action_plan,
            "intencion": "accion",
            "fuentes": [],
            "requires_human_review": False,
            "confidence": 1.0,
        }

    # Modo consulta: usar RAG.
    resultado = rag_query(query, k=3)
    return {
        "respuesta": resultado["answer"],
        "fuentes": resultado["sources"],
        "intencion": "onboarding",
        "confidence": 0.95,
    }
