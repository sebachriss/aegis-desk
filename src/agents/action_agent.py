"""Action Agent: nodo del grafo que ejecuta acciones (crear tickets, enviar emails).

Usa un agente ReAct con las herramientas de tickets y email.
El LLM decide qué herramienta usar y con qué argumentos.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.agents.state import AgentState
from src.llm.providers import get_llm
from src.tools.email import enviar_email
from src.tools.tickets import buscar_ticket, crear_ticket, listar_tickets

SYSTEM_PROMPT = """Eres el agente de acciones de Aegis Corp.
Tu trabajo es ejecutar acciones solicitadas por los empleados.

Puedes:
  - Crear tickets de soporte
  - Listar tickets existentes
  - Buscar un ticket por ID
  - Enviar emails internos

Usa las herramientas disponibles para completar las solicitudes.
Responde de forma clara y concisa en español, confirmando lo que hiciste.
"""


def action_node(state: AgentState) -> dict:
    """Nodo del grafo: ejecuta acciones con tools (tickets, email).

    Crea un agente ReAct con las tools de tickets y email,
    le pasa la solicitud del usuario, y devuelve la confirmación.
    """
    llm = get_llm(temperature=0)

    agent = create_react_agent(
        model=llm,
        tools=[crear_ticket, listar_tickets, buscar_ticket, enviar_email],
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )

    query = state["query"]

    result = agent.invoke({
        "messages": [HumanMessage(content=query)],
    })

    respuesta = result["messages"][-1].content

    return {
        "respuesta": respuesta,
        "fuentes": [],
    }
