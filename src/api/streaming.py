"""Generador de eventos Server-Sent Events (SSE) para /chat/stream.

Convierte el flujo de eventos de LangGraph (`graph.astream` con `stream_mode`)
en un stream tipado de eventos SSE:
  - node: nodo que se está ejecutando
  - token: chunk de texto del worker final (rag/chat)
  - interrupt: el grafo se pausó en HITL
  - done: respuesta final equivalente a ChatResponse
  - error: mensaje genérico, sin stack trace
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import Request
from langgraph.types import Interrupt

from src.config import get_settings
from src.db import hitl_queue as hitl_db
from src.observability.tracing import trace_execution
from src.security.pii_filter import filter_pii

NODE_LABELS = {
    "security": "Verificando seguridad...",
    "supervisor": "Clasificando intención...",
    "rag_agent": "Buscando en documentos...",
    "data_agent": "Consultando datos...",
    "action_planner": "Planificando acción...",
    "chat_agent": "Generando respuesta...",
    "critic": "Revisando respuesta...",
    "hitl_review": "Esperando aprobación...",
    "action_executor": "Ejecutando acción...",
}

# Workers cuyos tokens de LLM se streamean al cliente.
# Se excluyen supervisor, crítico, data y action para no exponer razonamiento interno.
ALLOWED_TOKEN_NODES = {"rag_agent", "chat_agent"}

# Modos de streaming de LangGraph que necesitamos.
STREAM_MODES = ["updates", "messages", "values"]


def _sse(event_type: str, payload: dict) -> str:
    """Serializa un evento SSE según el formato del plan."""
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_chat_events(
    graph,
    query: str,
    user: dict,
    request: Request,
    thread_id: str,
    timeout: float | None = None,
) -> AsyncIterator[str]:
    """Genera eventos SSE para una consulta al grafo.

    Args:
        graph: Grafo compilado de LangGraph (debe soportar .astream()).
        query: Mensaje del usuario.
        user: Diccionario con username y role.
        request: Request de FastAPI (para correlation_id).
        thread_id: ID del thread.
        timeout: Timeout en segundos. Si es None, usa config.

    Yields:
        Strings con eventos SSE listos para enviar.
    """
    settings = get_settings()
    timeout = timeout or settings.api_chat_timeout_seconds
    user_id = user["username"]
    role = user["role"]
    correlation_id = getattr(request.state, "correlation_id", None)
    start = time.time()

    inputs = {
        "messages": [],
        "query": query,
        "user_id": user_id,
        "role": role,
        "intencion": "",
        "respuesta": "",
        "fuentes": [],
        "confidence": 0.0,
        "requires_human_review": False,
        "retries": 0,
        "action_retries": 0,
        "tool_name": None,
        "authorization_decision": None,
        "action_plan": None,
        "approved_by": None,
        "approved_at": None,
    }
    config = {"configurable": {"thread_id": thread_id}}

    # Estado acumulado del grafo: empieza como copia de inputs y se actualiza
    # con las salidas de cada nodo.
    state: dict[str, Any] = dict(inputs)
    final_state: dict[str, Any] | None = None
    interrupted = False
    interrupt_value: Any = None
    traced = False
    emitted_nodes: set[str] = set()

    try:
        async with asyncio.timeout(timeout):
            async for part in graph.astream(
                inputs,
                config=config,
                stream_mode=STREAM_MODES,
                version="v2",
            ):
                part_type = part.get("type")
                data = part.get("data")

                # values: snapshot completo del estado, incluye interrupts.
                if part_type == "values" and isinstance(data, dict):
                    state.update(data)
                    final_state = data
                    interrupts = part.get("interrupts") or data.get("__interrupt__")
                    if interrupts:
                        interrupted = True
                        interrupt_value = interrupts

                # updates: nodo completado + actualización parcial de estado.
                elif part_type == "updates" and isinstance(data, dict):
                    for node_name, update in data.items():
                        if node_name in NODE_LABELS and node_name not in emitted_nodes:
                            emitted_nodes.add(node_name)
                            yield _sse("node", {"node": node_name, "label": NODE_LABELS[node_name]})
                        if isinstance(update, dict):
                            state.update(update)

                # messages: token (o mensaje completo) del LLM con metadata.
                elif part_type == "messages" and isinstance(data, tuple) and len(data) == 2:
                    message, metadata = data
                    source_node = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
                    if source_node in NODE_LABELS and source_node not in emitted_nodes:
                        emitted_nodes.add(source_node)
                        yield _sse("node", {"node": source_node, "label": NODE_LABELS[source_node]})
                    if source_node in ALLOWED_TOKEN_NODES:
                        token = getattr(message, "content", "") or ""
                        if token:
                            yield _sse("token", {"token": token})

    except asyncio.TimeoutError:
        elapsed = time.time() - start
        yield _sse("error", {"type": "timeout", "message": "La solicitud excedió el tiempo máximo de espera."})
        await asyncio.to_thread(
            trace_execution,
            query=query,
            intencion="bloqueado",
            respuesta="Timeout: la solicitud excedio el tiempo maximo",
            confidence=0.0,
            fuentes=[],
            retries=0,
            elapsed_seconds=elapsed,
            user_id=user_id,
            role=role,
            tool_name=None,
            authorization_decision="timeout",
            action_plan=None,
            approved_by=None,
            approved_at=None,
            correlation_id=correlation_id,
            block_reason="timeout",
        )
        traced = True
        return
    except Exception:
        elapsed = time.time() - start
        yield _sse("error", {"type": "internal", "message": "Error interno del servidor"})
        await asyncio.to_thread(
            trace_execution,
            query=query,
            intencion="error",
            respuesta="Error interno del servidor",
            confidence=0.0,
            fuentes=[],
            retries=0,
            elapsed_seconds=elapsed,
            user_id=user_id,
            role=role,
            tool_name=None,
            authorization_decision="error",
            action_plan=None,
            approved_by=None,
            approved_at=None,
            correlation_id=correlation_id,
            block_reason="error",
        )
        traced = True
        return

    # Usa el estado final si está disponible; si no, el acumulado.
    if isinstance(final_state, dict):
        state = final_state

    # HITL: el grafo se interrumpió
    if interrupted or state.get("__interrupt__"):
        interrupted = True
        iv = interrupt_value or state.get("__interrupt__")
        if isinstance(iv, tuple) and iv:
            iv = iv[0]
        resumen = iv.value if isinstance(iv, Interrupt) else "Acción requiere aprobación humana."

        await asyncio.to_thread(
            hitl_db.enqueue,
            thread_id,
            query=query,
            intencion=state.get("intencion") or "accion",
            action_plan=state.get("action_plan"),
            user=user,
        )

        yield _sse("interrupt", {"thread_id": thread_id, "resumen": str(resumen)})

    # Prepara respuesta final
    raw_respuesta = state.get("respuesta", "")
    if interrupted:
        raw_respuesta = "⏸️ Tu solicitud requiere aprobación humana. Pendiente de revisión."

    respuesta_filtrada, _ = filter_pii(raw_respuesta)
    elapsed = time.time() - start

    done_payload = {
        "thread_id": thread_id,
        "intencion": state.get("intencion") or ("" if not interrupted else "accion"),
        "respuesta": respuesta_filtrada,
        "confidence": state.get("confidence", 0.0),
        "fuentes": state.get("fuentes", []),
        "elapsed_seconds": round(elapsed, 2),
        "requires_hitl": interrupted,
    }
    yield _sse("done", done_payload)

    # Trace final (una sola vez por request)
    if not traced:
        trace_intencion = state.get("intencion") or "chat"
        trace_respuesta = respuesta_filtrada
        if interrupted:
            trace_respuesta = "⏸️ HITL pendiente de aprobacion"
            trace_intencion = state.get("intencion") or "accion"
        await asyncio.to_thread(
            trace_execution,
            query=query,
            intencion=trace_intencion,
            respuesta=trace_respuesta,
            confidence=state.get("confidence", 0.0),
            fuentes=state.get("fuentes", []),
            retries=state.get("retries", 0) + state.get("action_retries", 0),
            elapsed_seconds=elapsed,
            user_id=user_id,
            role=role,
            tool_name=state.get("tool_name"),
            authorization_decision=state.get("authorization_decision"),
            action_plan=state.get("action_plan"),
            approved_by=state.get("approved_by"),
            approved_at=state.get("approved_at"),
            correlation_id=correlation_id,
            block_reason=state.get("block_reason"),
        )
