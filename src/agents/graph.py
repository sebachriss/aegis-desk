"""Grafo multi-agente: ensambla seguridad + supervisor + workers + crítico + HITL en LangGraph.

Estructura:
  START → security → supervisor → (rag | datos | accion | chat) → crítico → (END | reintento | hitl)
              ↓                                                                        ↓
         bloqueado → END                                                              ↓
                                                                              hitl_review → END

El nodo de seguridad verifica prompt injection y rate limit antes de procesar.
El supervisor clasifica la intención y enruta a un worker (verificando RBAC).
El worker genera la respuesta.
El crítico evalúa la respuesta:
  - Buena → END
  - Mala con retries disponibles → vuelve al worker
  - Mala sin retries → hitl_review (revisión humana) → END
  - Acciones sensibles (intencion=accion) → hitl_review → END
"""

from langgraph.graph import END, StateGraph

from src.agents.action_agent import action_node
from src.agents.chat_agent import chat_node
from src.agents.critic_agent import critic_node
from src.agents.data_agent import data_node
from src.agents.hitl_node import hitl_node
from src.agents.rag_agent import rag_node
from src.agents.security_node import security_node
from src.agents.state import AgentState
from src.agents.supervisor import supervisor_node
from src.security.rbac import can_access


def route_from_security(state: AgentState) -> str:
    """Edge condicional: decide si continuar al supervisor o bloquear.

    Si el nodo de seguridad marcó la intención como 'bloqueado', ir a END.
    Si no, continuar al supervisor.
    """
    if state.get("intencion") == "bloqueado":
        return END
    return "supervisor"


def route_from_supervisor(state: AgentState) -> str:
    """Edge condicional: decide a qué worker ir según la intención.

    Verifica RBAC: si el rol del usuario no tiene permiso para la intención,
    redirige a chat_agent con un mensaje de acceso denegado.
    """
    intencion = state["intencion"]
    role = state.get("role", "empleado")

    # Verificar permisos del rol
    if not can_access(role, intencion):
        # El empleado no tiene acceso a esta intención (ej: datos requiere admin)
        return "chat_agent"

    routing = {
        "rag": "rag_agent",
        "datos": "data_agent",
        "accion": "action_agent",
        "chat": "chat_agent",
    }

    return routing.get(intencion, "chat_agent")


def route_from_worker(state: AgentState) -> str:
    """Edge condicional después del worker: decide si necesita crítico o va directo a END.

    - Si intención es 'chat' y confidence >= 0.9: respuesta directa, sin crítico (ahorra ~3s)
    - Resto: pasa por crítico para evaluación de calidad
    """
    intencion = state.get("intencion", "chat")
    confidence = state.get("confidence", 1.0)

    if intencion == "chat" and confidence >= 0.9:
        return END
    return "critic"


def route_from_critic(state: AgentState) -> str:
    """Edge condicional: decide si la respuesta es final, necesita reintento, o HITL.

    - Si requires_human_review → hitl_review (revisión humana)
    - Si intención es accion y confidence alta → hitl_review (acciones siempre revisadas)
    - Si confidence >= 0.7 → END
    - Si confidence < 0.7 y retries < 2 → volver al worker
    - Si confidence < 0.7 y retries >= 2 → hitl_review (último recurso)
    """
    confidence = state.get("confidence", 1.0)
    requires_human = state.get("requires_human_review", False)
    retries = state.get("retries", 0)
    intencion = state.get("intencion", "chat")

    # Solo acciones sensibles van a HITL (ej: enviar email)
    # Tickets (crear/listar/buscar) son acciones rutinarias que no necesitan aprobación
    # Este check va ANTES del requires_human porque el crítico puede marcar
    # revisión para acciones por precaución, pero los tickets no la necesitan
    if intencion == "accion" and confidence >= 0.7:
        respuesta = state.get("respuesta", "").lower()
        email_action_patterns = [
            "email enviado", "correo enviado", "enviado a", "he enviado",
            "enviado correctamente", "enviado exitosamente",
            "email ha sido enviado", "correo ha sido enviado",
        ]
        if any(p in respuesta for p in email_action_patterns):
            return "hitl_review"
        return END

    # Si el crítico marcó revisión humana explícita (y no es acción rutinaria)
    if requires_human:
        return "hitl_review"

    # Si la confianza es alta (y no es accion), la respuesta es buena
    if confidence >= 0.7:
        return END

    # Si la confianza es baja pero ya agotó los reintentos → revisión humana
    if retries >= 2:
        return "hitl_review"

    # Si la confianza es baja y quedan reintentos, volver al worker
    routing = {
        "rag": "rag_agent",
        "datos": "data_agent",
        "accion": "action_agent",
        "chat": "chat_agent",
    }

    return routing.get(intencion, "chat_agent")


def build_graph(checkpointer=None):
    """Construye y compila el grafo multi-agente.

    Args:
        checkpointer: Checkpointer de LangGraph (ej: MemorySaver).
            Necesario para HITL (interrupt pausa el grafo y guarda estado).

    Returns:
        Grafo compilado de LangGraph listo para usar con .invoke().
    """
    # 1. Crear el grafo con el estado compartido
    graph = StateGraph(AgentState)

    # 2. Añadir nodos
    graph.add_node("security", security_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("rag_agent", rag_node)
    graph.add_node("data_agent", data_node)
    graph.add_node("action_agent", action_node)
    graph.add_node("chat_agent", chat_node)
    graph.add_node("critic", critic_node)
    graph.add_node("hitl_review", hitl_node)

    # 3. Añadir edges
    # START → security
    graph.set_entry_point("security")

    # security → (condicional) → supervisor o END (bloqueado)
    graph.add_conditional_edges(
        "security",
        route_from_security,
        {
            "supervisor": "supervisor",
            END: END,
        },
    )

    # supervisor → (condicional) → worker
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "rag_agent": "rag_agent",
            "data_agent": "data_agent",
            "action_agent": "action_agent",
            "chat_agent": "chat_agent",
        },
    )

    # Cada worker → crítico (excepto chat simple que puede ir directo a END)
    graph.add_edge("rag_agent", "critic")
    graph.add_edge("data_agent", "critic")
    graph.add_edge("action_agent", "critic")
    graph.add_conditional_edges(
        "chat_agent",
        route_from_worker,
        {
            "critic": "critic",
            END: END,
        },
    )

    # crítico → (condicional) → END, worker (reintento), o hitl_review
    graph.add_conditional_edges(
        "critic",
        route_from_critic,
        {
            "rag_agent": "rag_agent",
            "data_agent": "data_agent",
            "action_agent": "action_agent",
            "chat_agent": "chat_agent",
            "hitl_review": "hitl_review",
            END: END,
        },
    )

    # hitl_review → END (después de la decisión humana, siempre termina)
    graph.add_edge("hitl_review", END)

    # 4. Compilar y devolver
    return graph.compile(checkpointer=checkpointer)


# Singleton del grafo compilado
_compiled_graph = None


def get_graph():
    """Devuelve el grafo compilado (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
