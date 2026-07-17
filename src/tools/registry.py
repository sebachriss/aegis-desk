"""Registro central de herramientas disponibles para los agentes.

Cada herramienta se registra aqui con un nombre unico.
El agente pide las tools al registry, no directamente del modulo.

Para añadir una nueva herramienta:
  1. Crear el archivo en src/tools/
  2. Importar la funcion @tool aqui
  3. Añadirla al diccionario TOOLS
"""

from src.tools.email import enviar_email
from src.tools.sql import consultar_sql_tool
from src.tools.tickets import buscar_ticket, crear_ticket, listar_tickets

# Registro de todas las herramientas disponibles
# Clave = nombre unico, Valor = funcion @tool de LangChain
TOOLS = {
    "crear_ticket": crear_ticket,
    "listar_tickets": listar_tickets,
    "buscar_ticket": buscar_ticket,
    "enviar_email": enviar_email,
    "consultar_sql": consultar_sql_tool,
}


def get_all_tools() -> list:
    """Devuelve todas las herramientas registradas como lista.

    El agente necesita una lista de tools para pasarselas al LLM.
    """
    return list(TOOLS.values())


def get_tools(names: list[str]) -> list:
    """Devuelve solo las herramientas especificadas por nombre.

    Util para RBAC (permisos por rol) en fases posteriores.

    Args:
        names: Lista de nombres de herramientas a obtener.

    Returns:
        Lista de funciones @tool correspondientes.
    """
    return [TOOLS[name] for name in names if name in TOOLS]
