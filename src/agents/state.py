"""Estado compartido del grafo multi-agente.

Todos los nodos (supervisor, workers, crítico) leen y escriben este estado.
Es un TypedDict: define qué campos existen y de qué tipo son.
LangGraph lo pasa de nodo en nodo automáticamente.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Estado que viaja por todo el grafo.

    Fields:
        messages: Historial de mensajes (LangGraph acumula automáticamente con add_messages).
        query: Pregunta original del usuario.
        intencion: Categoria clasificada por el supervisor: "rag", "datos", "accion", "chat".
        respuesta: Respuesta generada por el worker (RAG agent, Data agent, etc).
        fuentes: Lista de fuentes usadas (chunks de RAG, tablas consultadas, etc).
        confidence: Nivel de confianza del crítico (0.0 a 1.0).
        requires_human_review: True si el crítico decide que necesita aprobación humana.
        retries: Contador de reintentos (el crítico puede pedir reintento, max 2).
    """
    # add_messages hace que LangGraph acumule mensajes en vez de sobreescribirlos
    # Annotated[list, add_messages] = "lista que se appenda, no se reemplaza"
    messages: Annotated[list, add_messages]
    query: str
    user_id: str
    role: str
    intencion: str
    respuesta: str
    fuentes: list[dict]
    confidence: float
    requires_human_review: bool
    retries: int
