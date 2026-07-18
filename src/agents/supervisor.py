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

# Patrones rápidos de datos: preguntas sobre la base de datos de empleados/tickets/departamentos.
# Tienen prioridad sobre RAG para evitar que consultas de SQL se routeen a documentos.
DATA_PATTERNS = [
    r"\b(cuántos|cuantas)\s+(empleados|departamentos|tickets|registros)\b",
    r"\b(quién es el empleado|quien es el empleado)\b",
    r"\b(empleado con (mayor|más)|mayor salario|más salario)\b",
    r"\b(presupuesto total|tickets (cerrados|abiertos)|registros de tickets)\b",
    r"\b(gana más|quien gana|mayor salario)\b",
]
_compiled_data = [re.compile(p, re.IGNORECASE) for p in DATA_PATTERNS]

# Patrones rápidos de RAG: preguntas sobre políticas, procedimientos, FAQ o equipos.
# Estas palabras clave indican que el usuario busca información documentada.
RAG_PATTERNS = [
    r"\b(política|politica|manual|procedimiento|faq|pregunta frecuente)\b",
    r"\b(pet fridays?|mascota)\b",
    r"\b(equipo nuevo|equipos nuevos|solicitar.*equipo|pedir.*equipo|laptop)\b",
    r"\b(contraseña|password|resetear|reset)\b",
    r"\b(vacaciones|días de vacaciones|teletrabajo|remoto)\b",
    r"\b(salario|sueldo|nómina)\b",
    r"\b(pérdida de equipo|perdí|perdi.*(laptop|equipo)|rob(o|aron)|extrav(i|io))\b",
    r"\b(cómo solicito|cómo pido|cómo accedo|cómo reporto|qué hago si)\b",
]
_compiled_rag = [re.compile(p, re.IGNORECASE) for p in RAG_PATTERNS]

# Palabras que indican una orden de acción explícita.
# Si aparecen junto a tickets/email/vacaciones/saldo, la intención es "accion".
ACTION_VERBS = re.compile(
    r"\b(crea|crear|envía|enviar|envie|lista|listar|listame|muestra|mostrar|busca|buscar|buscame|manda|mandar|"
    r"solicita|solicitar|solicitame|pide|pedir|pedirme|reserva|reservar|reservame|consulta|consultar|dame|ver|revisar)\b",
    re.IGNORECASE,
)
ACTION_NOUNS = re.compile(r"\b(ticket|tickets|email|correo|mail|vacaciones|saldo)\b", re.IGNORECASE)

# Patrón adicional para "saldo de vacaciones" sin verbo de acción explícito.
VACACIONES_SALDO = re.compile(
    r"\b(saldo\s+(de\s+)?vacaciones|saldo\s+vacaciones|mi\s+saldo|consultar.*saldo|saber.*saldo)\b",
    re.IGNORECASE,
)


def _is_trivial_chat(query: str) -> bool:
    """Detecta si el mensaje es un saludo/despedida trivial sin usar LLM."""
    stripped = query.strip().lower()
    if len(stripped) > 60:
        return False
    return any(p.match(stripped) for p in _compiled_chat)


def _is_action_query(query: str) -> bool:
    """Heurística rápida: detecta órdenes de acción sobre tickets/email/vacaciones."""
    return (ACTION_VERBS.search(query) and ACTION_NOUNS.search(query)) or VACACIONES_SALDO.search(query)


def _is_data_query(query: str) -> bool:
    """Heurística rápida: detecta consultas de base de datos."""
    return any(p.search(query) for p in _compiled_data)


def _is_rag_query(query: str) -> bool:
    """Heurística rápida: detecta consultas que buscan info documentada."""
    return any(p.search(query) for p in _compiled_rag)


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

- **rag**: El usuario pregunta sobre políticas, manuales, procedimientos, FAQ de la empresa, o cómo hacer algo dentro de la empresa (equipos, contraseñas, teletrabajo, vacaciones, pérdida de equipo).
  Ej: "¿Cuántos días de vacaciones tengo?", "¿Cómo reseteo mi contraseña?", "¿Puedo traer a mi mascota?", "¿Cómo solicito un equipo nuevo?", "¿Qué hago si pierdo mi laptop?"

- **datos**: El usuario pregunta sobre datos que están en la base de datos SQL (empleados, departamentos, números, estadísticas, presupuestos).
  Ej: "¿Cuántos empleados hay?", "¿Quién gana más en Ventas?", "¿Cuál es el presupuesto de IT?"
  NOTA: listar tickets o buscar tickets NO es "datos" — es "accion".

- **accion**: El usuario pide explícitamente ejecutar una acción con herramientas: crear ticket, listar tickets, buscar ticket, enviar email, consultar saldo de vacaciones, solicitar vacaciones.
  Ej: "Crea un ticket de alta prioridad", "Envía un email a RRHH", "Lista los tickets abiertos", "Busca el ticket 1", "Quiero solicitar vacaciones del 1 al 5 de agosto", "¿Cuál es mi saldo de vacaciones?"
  Una frase como "Pérdida de laptop" o "Mi laptop no funciona" es una consulta de información (rag) a menos que diga explícitamente "crea un ticket" o "reporta".

- **chat**: Saludos, conversación general, o preguntas que no encajan en las anteriores.
  Ej: "Hola", "¿Qué tal?", "Gracias"

Reglas clave:
1. Si la pregunta busca información documentada (políticas, manuales, FAQ, procedimientos), es **rag**.
2. Si la pregunta menciona "tickets", "email", "vacaciones", "saldo" o pide explícitamente "crea"/"envía"/"lista"/"busca"/"solicita"/"consulta", es **accion**.
3. "¿Cuál es la política de vacaciones?" es **rag** (pregunta por normativa). "¿Cuál es mi saldo de vacaciones?" o "Quiero solicitar vacaciones" es **accion**.
4. Solo es **datos** si pregunta por empleados, departamentos, presupuestos o números de la DB.

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

    # Fast path: órdenes de acción sobre tickets/email
    if _is_action_query(query):
        return {
            "intencion": "accion",
            "confidence": 0.95,
        }

    # Fast path: consultas de datos obvias tienen prioridad
    if _is_data_query(query):
        return {
            "intencion": "datos",
            "confidence": 0.95,
        }

    # Fast path: órdenes de acción sobre tickets/email
    if _is_action_query(query):
        return {
            "intencion": "accion",
            "confidence": 0.95,
        }

    # Fast path: consultas de datos obvias tienen prioridad
    if _is_data_query(query):
        return {
            "intencion": "datos",
            "confidence": 0.95,
        }

    # Fast path: consultas de RAG obvias por palabras clave
    if _is_rag_query(query) and not re.search(r"\b(crea|crear|envía|enviar|lista|listar|busca|buscar)\b", query, re.IGNORECASE):
        return {
            "intencion": "rag",
            "confidence": 0.95,
        }

    # Slow path: LLM para clasificar
    llm = get_fast_llm()
    llm_estructurado = llm.with_structured_output(ClasificacionSupervisor, method="function_calling")

    try:
        result = llm_estructurado.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=query),
        ])
    except Exception:
        # Fallback seguro: si el LLM no logra llamar a la función (ej. prompt injection
        # o formato inválido), dejar que el chat_agent maneje la consulta con sus reglas de seguridad.
        return {
            "intencion": "chat",
            "confidence": 1.0,
        }

    return {
        "intencion": result.intencion,
        "confidence": result.confidence,
    }
