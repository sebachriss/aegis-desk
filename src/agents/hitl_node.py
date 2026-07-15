"""Nodo HITL (Human-in-the-Loop): pausa el grafo para aprobación humana.

Se activa cuando:
  - La intención es "accion" (crear tickets, enviar emails — acciones sensibles)
  - El crítico marca requires_human_review=True (confidence muy baja)

Usa interrupt() de LangGraph para pausar la ejecución.
El humano responde con Command(resume="approve") o Command(resume="reject").
"""

from langgraph.types import interrupt

from src.agents.state import AgentState


def hitl_node(state: AgentState) -> dict:
    """Nodo del grafo: pausa para aprobación humana.

    Muestra la acción propuesta y espera la decisión del humano.
    LangGraph guarda el estado y pausa. Cuando el humano responde
    con Command(resume=...), el grafo continúa desde aquí.

    Solo pausa para acciones sensibles (email). Tickets pasan directo
    sin aprobación.

    Returns:
        Diccionario con la decisión del humano:
        - approved: True/False
        - Si se rechaza, devuelve respuesta de rechazo al usuario.
    """
    query = state["query"]
    respuesta = state.get("respuesta", "")
    intencion = state.get("intencion", "")

    # Solo pausar para acciones sensibles (envío de email/correo)
    # Tickets (crear/listar/buscar) no necesitan aprobación humana
    # Buscar verbos de acción de email, no la palabra "email" suelta
    # (puede aparecer en títulos de tickets: "Email no llega")
    respuesta_lower = respuesta.lower()
    email_action_patterns = [
        "email enviado", "correo enviado", "enviado a", "he enviado",
        "enviado correctamente", "enviado exitosamente",
        "email ha sido enviado", "correo ha sido enviado",
    ]
    if not any(p in respuesta_lower for p in email_action_patterns):
        return {
            "respuesta": respuesta,
            "requires_human_review": False,
        }

    # Construir el resumen de lo que el agente quiere hacer
    resumen = f"""
=== REVISIÓN HUMANA REQUERIDA ===

Intención: {intencion}
Pregunta del usuario: {query}

Respuesta propuesta del agente:
{respuesta}

¿Aprobar esta respuesta? (approve / reject)
"""

    # interrupt() pausa la ejecución aquí.
    # El valor que se pasa es lo que ve el humano (para decidir).
    # El valor que devuelve es lo que el humano envía con Command(resume=...).
    decision = interrupt(resumen)

    if decision == "approve":
        # El humano aprobó — devolver la respuesta tal cual
        return {
            "respuesta": respuesta,
            "requires_human_review": False,
        }
    else:
        # El humano rechazó — devolver mensaje de rechazo
        return {
            "respuesta": "⛔ Tu solicitud fue revisada por un supervisor y rechazada. Para más información, contacta al equipo de soporte.",
            "requires_human_review": False,
        }
