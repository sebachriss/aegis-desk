"""Data Agent: nodo del grafo que responde consultas sobre la base de datos.

Usa un agente ReAct con la herramienta consultar_sql.
El LLM decide qué query SQL escribir, la ejecuta, e interpreta el resultado.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.agents.state import AgentState
from src.llm.providers import get_llm
from src.security.rbac import get_allowed_tools, validate_role

SYSTEM_PROMPT = """Eres el agente de datos de Aegis Corp.
Tu trabajo es responder consultas sobre la base de datos de la empresa.

Tablas disponibles:
  - empleados (id, nombre, email, departamento_id, salario)
  - departamentos (id, nombre, presupuesto)
  - tickets (id, titulo, prioridad, estado, empleado_id)

Usa la herramienta consultar_sql para ejecutar consultas SELECT.
Reglas:
- Responde de forma clara y concisa en español.
- Si el resultado contiene valores redactados (***), NO inventes el dato original. Simplemente indica que esa información está oculta por privacidad y responde con lo que sí puedes decir (por ejemplo, el nombre).

Ejemplos de consultas:
- "¿Cuántos empleados hay en Ventas?" -> SELECT COUNT(*) AS total FROM empleados WHERE departamento_id = (SELECT id FROM departamentos WHERE nombre = 'Ventas')
- "¿Cuántos empleados hay en total?" -> SELECT COUNT(*) AS total FROM empleados
- "¿Quién gana más?" -> SELECT nombre, salario FROM empleados ORDER BY salario DESC LIMIT 1
- "¿Cuántos tickets cerrados hay?" -> SELECT COUNT(*) AS total FROM tickets WHERE estado = 'cerrado'
"""


def _extract_tool_name(messages: list) -> str | None:
    """Extrae el nombre de la última tool invocada desde el historial de mensajes."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            return msg.tool_calls[0].get("name")
    return None


def _extract_tool_result(messages: list) -> str:
    """Extrae el contenido del último ToolMessage para pasarlo como fuente al crítico."""
    for msg in reversed(messages):
        # ToolMessage en LangChain tiene atributo 'content' y 'name'
        if getattr(msg, "type", None) == "tool" or getattr(msg, "__class__", "").__name__ == "ToolMessage":
            return str(getattr(msg, "content", ""))
    return ""


def data_node(state: AgentState) -> dict:
    """Nodo del grafo: responde usando SQL sobre la base de datos.

    Aplica RBAC: el agente recibe solo la tool consultar_sql si su rol la permite.
    Registra el nombre de la tool invocada y la decision de autorizacion.
    """
    role = state.get("role", "empleado")

    # Fail closed: roles desconocidos no acceden a datos
    if not validate_role(role):
        return {
            "respuesta": "⛔ Rol inválido o no especificado. Contacta al administrador.",
            "fuentes": [],
            "tool_name": None,
            "authorization_decision": "unknown_role",
            "confidence": 1.0,
        }

    allowed_tools = get_allowed_tools(role)
    sql_tools = [t for t in allowed_tools if getattr(t, "name", None) == "consultar_sql"]

    if not sql_tools:
        return {
            "respuesta": "⛔ No tienes permiso para consultar la base de datos.",
            "fuentes": [],
            "tool_name": "consultar_sql",
            "authorization_decision": "denied",
            "confidence": 1.0,
        }

    llm = get_llm(temperature=0)

    agent = create_react_agent(
        model=llm,
        tools=sql_tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )

    query = state["query"]

    result = agent.invoke({
        "messages": [HumanMessage(content=query)],
    })

    respuesta = result["messages"][-1].content
    tool_name = _extract_tool_name(result["messages"])

    tool_result = _extract_tool_result(result["messages"])
    fuentes = [{"source": "aegis.db (SQLite)"}]
    if tool_result:
        fuentes.append({"source": "consultar_sql", "content": tool_result[:1000]})

    return {
        "respuesta": respuesta,
        "fuentes": fuentes,
        "tool_name": tool_name,
        "authorization_decision": "allowed",
    }
