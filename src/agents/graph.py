"""Grafo multi-agente: ensambla seguridad + supervisor + workers + critico + HITL en LangGraph.

Estructura:
  START -> security -> supervisor -> (rag | datos | accion | chat) -> critico -> (END | reintento | hitl)
              |                                                                          |
         bloqueado -> END                                                           hitl_review
                                                                                        |
                                                                                action_executor -> END

Fase 1 (SEC-01): RBAC real de tools. Los workers reciben solo las tools permitidas por rol.
Fase 2 (SEC-02): separa action_planner de action_executor. Acciones de alto riesgo pasan
por HITL antes de ejecutarse. La deteccion de HITL ya no depende de frases del LLM.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.action_agent import action_executor_node, action_planner_node
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

    Si el nodo de seguridad marco la intencion como 'bloqueado', ir a END.
    Si no, continuar al supervisor.
    """
    if state.get("intencion") == "bloqueado":
        return END
    return "supervisor"


def route_from_supervisor(state: AgentState) -> str:
    """Edge condicional: decide a que worker ir segun la intencion.

    Verifica RBAC a nivel de intencion. Si el rol no tiene permiso,
    redirige a chat_agent con un mensaje de acceso denegado.
    """
    intencion = state["intencion"]
    role = state.get("role", "empleado")

    try:
        has_access = can_access(role, intencion)
    except ValueError:
        # Rol desconocido: fail closed
        return "chat_agent"

    if not has_access:
        return "chat_agent"

    routing = {
        "rag": "rag_agent",
        "datos": "data_agent",
        "accion": "action_planner",
        "chat": "chat_agent",
    }

    return routing.get(intencion, "chat_agent")


def route_from_worker(state: AgentState) -> str:
    """Edge condicional despues del worker: decide si necesita critico o va directo a END.

    - Si intencion es 'chat' y confidence >= 0.9: respuesta directa, sin critico (ahorra ~3s)
    - Resto: pasa por critico para evaluacion de calidad
    """
    intencion = state.get("intencion", "chat")
    confidence = state.get("confidence", 1.0)

    if intencion == "chat" and confidence >= 0.9:
        return END
    return "critic"


def route_from_planner(state: AgentState) -> str:
    """Edge condicional: decide si una accion requiere HITL o puede ejecutarse directo.

    - Si action_plan no existe, termina.
    - Si risk_level es 'high', pausa para revision humana.
    - Si es 'low'/'medium', ejecuta directamente.
    """
    action_plan = state.get("action_plan")
    if not action_plan:
        return END

    risk_level = action_plan.get("risk_level", "low")
    if risk_level == "high":
        return "hitl_review"
    return "action_executor"


def route_from_hitl(state: AgentState) -> str:
    """Edge condicional despues de HITL: ejecuta si fue aprobada, termina si fue rechazada."""
    action_plan = state.get("action_plan")
    if action_plan and action_plan.get("approval_status") == "approved":
        return "action_executor"
    return END


def route_from_critic(state: AgentState) -> str:
    """Edge condicional: decide si la respuesta es final, necesita reintento, o HITL.

    Fase 2: la logica de HITL por acciones ya no depende de frases del LLM.
    Las acciones son ruteadas por action_plan desde route_from_planner.
    Este nodo solo maneja reintentos y revision humana por baja confianza.
    """
    confidence = state.get("confidence", 0.0)
    requires_human = state.get("requires_human_review", False)
    requires_retry = state.get("requires_retry", True)
    intencion = state.get("intencion", "chat")

    # HITL solo para acciones con action_plan.
    # RAG/chat/datos con baja confianza terminan con la mejor respuesta disponible.
    if requires_human and intencion == "accion" and state.get("action_plan"):
        return "hitl_review"

    # Si la confianza es alta, la respuesta es buena
    if confidence >= 0.7:
        return END

    # Si el crítico no pide reintento y la confianza sigue baja, terminamos.
    if not requires_retry:
        return END

    # Para acciones, si ya se ejecutaron no las re-lanzamos (evita duplicar side effects).
    if intencion == "accion":
        action_plan = state.get("action_plan")
        if action_plan and action_plan.get("execution_status") == "succeeded":
            return "action_executor"

    routing = {
        "rag": "rag_agent",
        "datos": "data_agent",
        "accion": "action_planner",
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

    # 2. Anadir nodos
    graph.add_node("security", security_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("rag_agent", rag_node)
    graph.add_node("data_agent", data_node)
    graph.add_node("action_planner", action_planner_node)
    graph.add_node("action_executor", action_executor_node)
    graph.add_node("chat_agent", chat_node)
    graph.add_node("critic", critic_node)
    graph.add_node("hitl_review", hitl_node)

    # 3. Anadir edges
    # START -> security
    graph.set_entry_point("security")

    # security -> (condicional) -> supervisor o END (bloqueado)
    graph.add_conditional_edges(
        "security",
        route_from_security,
        {
            "supervisor": "supervisor",
            END: END,
        },
    )

    # supervisor -> (condicional) -> worker
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "rag_agent": "rag_agent",
            "data_agent": "data_agent",
            "action_planner": "action_planner",
            "chat_agent": "chat_agent",
        },
    )

    # Cada worker -> critico (excepto chat simple que puede ir directo a END)
    graph.add_edge("rag_agent", "critic")
    graph.add_edge("data_agent", "critic")
    graph.add_conditional_edges(
        "action_planner",
        route_from_planner,
        {
            "hitl_review": "hitl_review",
            "action_executor": "action_executor",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "chat_agent",
        route_from_worker,
        {
            "critic": "critic",
            END: END,
        },
    )

    # critico -> (condicional) -> END, worker (reintento), action_executor o hitl_review
    graph.add_conditional_edges(
        "critic",
        route_from_critic,
        {
            "rag_agent": "rag_agent",
            "data_agent": "data_agent",
            "action_planner": "action_planner",
            "chat_agent": "chat_agent",
            "action_executor": "action_executor",
            "hitl_review": "hitl_review",
            END: END,
        },
    )

    # hitl_review -> action_executor o END
    graph.add_conditional_edges(
        "hitl_review",
        route_from_hitl,
        {
            "action_executor": "action_executor",
            END: END,
        },
    )

    # action_executor -> END
    graph.add_edge("action_executor", END)

    # 4. Compilar y devolver
    return graph.compile(checkpointer=checkpointer)


# Singleton del grafo compilado
_compiled_graph = None


def get_graph():
    """Devuelve el grafo compilado (singleton) con checkpointer en memoria.

    El checkpointer es necesario para HITL (interrupt).
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph(checkpointer=MemorySaver())
    return _compiled_graph
