"""Estado compartido del grafo multi-agente.

Todos los nodos (supervisor, workers, crítico) leen y escriben este estado.
Es un TypedDict: define qué campos existen y de qué tipo son.
LangGraph lo pasa de nodo en nodo automáticamente.
"""

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Estado que viaja por todo el grafo.

    Fields:
        messages: Historial de mensajes (LangGraph acumula automáticamente con add_messages).
        query: Pregunta original del usuario.
        user_id: Identificador del usuario autenticado.
        role: Rol del usuario ("empleado" o "admin").
        intencion: Categoria clasificada por el supervisor: "rag", "datos", "accion", "chat".
        respuesta: Respuesta generada por el worker (RAG agent, Data agent, etc).
        fuentes: Lista de fuentes usadas (chunks de RAG, tablas consultadas, etc).
        confidence: Nivel de confianza del crítico (0.0 a 1.0).
        requires_human_review: True si el crítico decide que necesita aprobación humana.
        requires_retry: True si el crítico pide otro intento de generación (evita loops infinitos).
        retries: Contador de reintentos de generación (el crítico puede pedir reintento, max 2).
        action_retries: Contador de reintentos específicos del action planner/executor.
        tool_name: Nombre de la herramienta invocada (si aplica).
        authorization_decision: Decision de autorizacion ("allowed", "denied", "unknown_role").
        action_plan: Plan estructurado de accion pendiente (Fase 2 HITL).
        approved_by: Usuario que aprobo una accion HITL.
        approved_at: Timestamp ISO de aprobacion HITL.
        block_reason: Motivo de bloqueo en el nodo de seguridad (prompt_injection, rate_limit, unknown_role).
        retry_after: Segundos sugeridos antes de reintentar tras un rate limit.
        retrieval_scores: Scores de similitud de los chunks recuperados (RAG).
        discarded: Número de chunks descartados por baja relevancia o fuente inválida (RAG).
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
    requires_retry: NotRequired[bool]
    retries: int
    action_retries: NotRequired[int]
    tool_name: str | None
    authorization_decision: str | None
    action_plan: dict | None
    approved_by: str | None
    approved_at: str | None
    block_reason: NotRequired[str | None]
    retry_after: NotRequired[int]
    retrieval_scores: NotRequired[list[float]]
    discarded: NotRequired[int]
