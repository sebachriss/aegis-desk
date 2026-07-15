"""Supervisor: clasifica la intención del usuario y enruta al agente correcto.

Usa structured output para devolver:
  - intencion: "rag", "datos", "accion", o "chat"
  - confidence: 0.0 a 1.0

El grafo usa este campo para decidir a qué nodo ir (conditional edge).
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

import re

from src.agents.state import AgentState
from src.llm.providers import get_fast_llm


# Patrones de saludos/mensajes triviales que no necesitan LLM para clasificar
# Security ya filtró prompt injection antes de llegar aquí
CHAT_PATTERNS = [
    r"^(hola|buenas|hey|hi|hello|qué tal|que tal|buenos días|buenas tardes|buenas noches)[\s!¡\.?]*$",
    r"^(gracias|muchas gracias|thanks|thank you|perfecto|genial|ok|vale|entendido)[\s!\.]*$",
    r"^(adiós|adios|chao|bye|nos vemos|hasta luego|me voy)[\s!\.]*$",
    r"^(qué puedes hacer|que puedes hacer|ayuda|help)[\s\?¿]*$",
]
_compiled_chat = [re.compile(p, re.IGNORECASE) for p in CHAT_PATTERNS]


def _is_trivial_chat(query: str) -> bool:
    """Detecta si el mensaje es un saludo/despedida trivial sin usar LLM."""
    stripped = query.strip().lower()
    if len(stripped) > 60:
        return False
    return any(p.match(stripped) for p in _compiled_chat)


# Schema de salida — el LLM tiene que rellenar esto
class ClasificacionSupervisor(BaseModel):
    """Clasificacion de la intencion del mensaje del usuario."""

    intencion: Literal["rag", "datos", "accion", "chat"] = Field(
        description=(
            "Categoria del mensaje:\n"
            "- rag: preguntas sobre politicas, manuales, FAQ de la empresa (documentos)\n"
            "- datos: consultas sobre datos en la base de datos (empleados, tickets, numeros)\n"
            "- accion: solicitudes de hacer algo (crear ticket, enviar email)\n"
            "- chat: saludos, conversacion general, o anything que no encaje en lo anterior"
        ),
    )
    confidence: float = Field(
        description="Confianza en la clasificacion, de 0.0 a 1.0",
    )


SYSTEM_PROMPT = """Eres el supervisor de Aegis Desk, un sistema de soporte interno.

Tu trabajo es clasificar la intención del mensaje del usuario en una de 4 categorías:

- **rag**: El usuario pregunta sobre políticas, manuales, procedimientos, o FAQ de la empresa.
  Ej: "¿Cuántos días de vacaciones tengo?", "¿Cómo reseteo mi contraseña?"

- **datos**: El usuario pregunta sobre datos que están en la base de datos SQL (empleados, departamentos, números, estadísticas, presupuestos).
  Ej: "¿Cuántos empleados hay?", "¿Quién gana más en Ventas?", "¿Cuál es el presupuesto de IT?"
  NOTA: listar tickets o buscar tickets NO es "datos" — es "accion".

- **accion**: El usuario pide ejecutar una acción con herramientas: crear ticket, listar tickets, buscar ticket, enviar email.
  Ej: "Crea un ticket de alta prioridad", "Envía un email a RRHH", "Lista los tickets abiertos", "Busca el ticket 1"

- **chat**: Saludos, conversación general, o preguntas que no encajan en las anteriores.
  Ej: "Hola", "¿Qué tal?", "Gracias"

Regla clave: si la pregunta menciona "tickets" o "email", es casi siempre "accion".
Solo es "datos" si pregunta por empleados, departamentos, o números de la DB.

Responde solo con la clasificación en formato JSON. No respondas la pregunta del usuario.
"""


def supervisor_node(state: AgentState) -> dict:
    """Nodo del grafo: clasifica la intención del usuario.

    Lee state["query"], la clasifica, y devuelve la intención + confidence.
    El grafo usa esto para decidir a qué worker enrutar.

    Fast path: si el mensaje es un saludo/despedida trivial, clasifica como
    'chat' sin llamar al LLM (ahorra ~3s). Security ya filtró injection antes.
    """
    query = state["query"]

    # Fast path: saludos triviales sin LLM
    if _is_trivial_chat(query):
        return {
            "intencion": "chat",
            "confidence": 1.0,
        }

    # Slow path: LLM para clasificar
    llm = get_fast_llm()
    llm_estructurado = llm.with_structured_output(ClasificacionSupervisor, method="function_calling")

    result = llm_estructurado.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=query),
    ])

    return {
        "intencion": result.intencion,
        "confidence": result.confidence,
    }
