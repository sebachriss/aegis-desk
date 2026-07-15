"""Data Agent: nodo del grafo que responde consultas sobre la base de datos.

Usa un agente ReAct con la herramienta consultar_sql.
El LLM decide qué query SQL escribir, la ejecuta, e interpreta el resultado.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.agents.state import AgentState
from src.llm.providers import get_llm
from src.tools.sql import consultar_sql

SYSTEM_PROMPT = """Eres el agente de datos de Aegis Corp.
Tu trabajo es responder consultas sobre la base de datos de la empresa.

Tablas disponibles:
  - empleados (id, nombre, email, departamento_id, salario)
  - departamentos (id, nombre, presupuesto)
  - tickets (id, titulo, prioridad, estado, empleado_id)

Usa la herramienta consultar_sql para ejecutar consultas SELECT.
Responde de forma clara y concisa en español.
"""


def data_node(state: AgentState) -> dict:
    """Nodo del grafo: responde usando SQL sobre la base de datos.

    Crea un agente ReAct con solo la herramienta consultar_sql,
    le pasa la pregunta del usuario, y devuelve la respuesta.
    """
    llm = get_llm(temperature=0)

    # Agente ReAct con SOLO la tool de SQL (no todas las tools)
    agent = create_react_agent(
        model=llm,
        tools=[consultar_sql],
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )

    query = state["query"]

    result = agent.invoke({
        "messages": [HumanMessage(content=query)],
    })

    # El último mensaje es la respuesta final del agente
    respuesta = result["messages"][-1].content

    return {
        "respuesta": respuesta,
        "fuentes": [{"source": "aegis.db (SQLite)"}],
    }
