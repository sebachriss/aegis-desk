"""Agente ReAct con function calling nativo.

El agente puede:
  1. Razonar sobre la pregunta del usuario
  2. Decidir qué herramienta llamar
  3. Ejecutar la herramienta
  4. Observar el resultado
  5. Repetir si necesita más información
  6. Responder al usuario

Usa create_react_agent de LangGraph que implementa el patrón ReAct
con function calling nativo del LLM (no prompt engineering manual).
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.llm.providers import get_llm
from src.security.rbac import get_allowed_tools, validate_role

# Prompt de sistema del agente
SYSTEM_PROMPT = """Eres Aegis, un asistente de soporte interno de Aegis Corp.

Puedes usar las herramientas disponibles para ayudar según tu rol:
- Crear, listar y buscar tickets de soporte
- Enviar emails internos (solo administradores)
- Consultar la base de datos de la empresa (solo SELECT, solo administradores)

Reglas:
1. Usa las herramientas cuando sea necesario. No inventes datos.
2. Si una herramienta devuelve un error, informe al usuario claramente.
3. Responde en español, de forma clara y concisa.
4. Si no tienes una herramienta para resolver la pregunta, dilo.
"""


def create_agent(role: str = "empleado"):
    """Crea y devuelve el agente ReAct configurado con tools filtradas por rol.

    Args:
        role: Rol del usuario ("empleado" o "admin").

    Returns:
        Agente ReAct de LangGraph listo para usar con .invoke().

    Raises:
        ValueError: Si el rol no es válido.
    """
    if not validate_role(role):
        raise ValueError(f"Rol desconocido: {role}")

    llm = get_llm(temperature=0)
    tools = get_allowed_tools(role)

    # create_react_agent crea un grafo LangGraph que implementa el ciclo:
    #   LLM decide -> ejecuta tool -> LLM observa -> repite o responde
    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )

    return agent


def run_agent(user_input: str, role: str = "empleado") -> dict:
    """Ejecuta el agente con un mensaje del usuario.

    Args:
        user_input: Pregunta o instrucción del usuario.
        role: Rol del usuario ("empleado" o "admin").

    Returns:
        Diccionario con: response (respuesta final), messages (historial completo).
    """
    agent = create_agent(role)

    result = agent.invoke({
        "messages": [HumanMessage(content=user_input)],
    })

    # El ultimo mensaje es la respuesta final del agente
    messages = result["messages"]
    final_response = messages[-1].content

    return {
        "response": final_response,
        "messages": messages,
    }
