"""Supervisor: clasifica la intención del usuario y enruta al agente correcto.

Usa structured output para devolver:
  - intencion: "rag", "datos", "accion", o "chat"
  - confidence: 0.0 a 1.0

El grafo usa este campo para decidir a qué nodo ir (conditional edge).
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.state import AgentState
from src.llm.providers import get_llm


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

Responde solo con la clasificación. No respondas la pregunta del usuario.
"""


def supervisor_node(state: AgentState) -> dict:
    """Nodo del grafo: clasifica la intención del usuario.

    Lee state["query"], la clasifica, y devuelve la intención + confidence.
    El grafo usa esto para decidir a qué worker enrutar.
    """
    llm = get_llm(temperature=0)
    llm_estructurado = llm.with_structured_output(ClasificacionSupervisor)

    # El último mensaje del historial es la pregunta del usuario
    query = state["query"]

    result = llm_estructurado.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=query),
    ])

    return {
        "intencion": result.intencion,
        "confidence": result.confidence,
    }
