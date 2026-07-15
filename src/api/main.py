"""FastAPI app para Aegis Desk.

Endpoints:
  POST /chat          — enviar mensaje (devuelve respuesta + metadata)
  GET  /chat/stream   — streaming SSE (token por token)
  GET  /hitl/pending  — listar threads con HITL pendiente
  POST /hitl/{thread_id}/approve — aprobar acción pendiente
  POST /hitl/{thread_id}/reject  — rechazar acción pendiente
  GET  /stats         — estadísticas de tracing
  GET  /health        — health check

HITL usa MemorySaver checkpointer con thread_id por conversación.
"""

import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from src.agents.graph import build_graph
from src.observability.tracing import get_stats, trace_execution
from src.security.rate_limiter import reset_user

# --- Setup ---

app = FastAPI(
    title="Aegis Desk API",
    description="Plataforma de soporte interno inteligente multi-agente",
    version="1.0.0",
)

# CORS para Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Checkpointer compartido para HITL (persiste entre requests en memoria)
_checkpointer = MemorySaver()
_graph = build_graph(checkpointer=_checkpointer)


# --- Schemas ---

class ChatRequest(BaseModel):
    query: str
    user_id: str = "api_user"
    role: str = "empleado"


class ChatResponse(BaseModel):
    thread_id: str
    intencion: str
    respuesta: str
    confidence: float
    fuentes: list[dict]
    elapsed_seconds: float
    requires_hitl: bool


class HITLDecision(BaseModel):
    decision: str  # "approve" o "reject"


# --- Endpoints ---


@app.get("/health")
async def health():
    return {"status": "ok", "service": "aegis-desk"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Envía un mensaje al agente y devuelve la respuesta.

    Si el grafo se pausa en HITL, devuelve requires_hitl=True
    y el thread_id para aprobar/rechazar después.
    """
    reset_user(req.user_id)

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    start = time.time()
    result = _graph.invoke({
        "messages": [],
        "query": req.query,
        "user_id": req.user_id,
        "role": req.role,
        "intencion": "",
        "respuesta": "",
        "fuentes": [],
        "confidence": 0.0,
        "requires_human_review": False,
        "retries": 0,
    }, config=config)
    elapsed = time.time() - start

    # Verificar si se pausó en HITL
    is_interrupted = bool(result.get("__interrupt__"))

    if is_interrupted:
        return ChatResponse(
            thread_id=thread_id,
            intencion=result.get("intencion", ""),
            respuesta="⏸️ Tu solicitud requiere aprobación humana. Pendiente de revisión.",
            confidence=result.get("confidence", 0.0),
            fuentes=result.get("fuentes", []),
            elapsed_seconds=round(elapsed, 2),
            requires_hitl=True,
        )

    # Registrar trace
    trace_execution(
        query=req.query,
        intencion=result.get("intencion", ""),
        respuesta=result.get("respuesta", "")[:500],
        confidence=result.get("confidence", 0.0),
        fuentes=result.get("fuentes", []),
        retries=result.get("retries", 0),
        elapsed_seconds=elapsed,
        user_id=req.user_id,
        role=req.role,
    )

    return ChatResponse(
        thread_id=thread_id,
        intencion=result.get("intencion", ""),
        respuesta=result.get("respuesta", ""),
        confidence=result.get("confidence", 0.0),
        fuentes=result.get("fuentes", []),
        elapsed_seconds=round(elapsed, 2),
        requires_hitl=False,
    )


@app.get("/hitl/pending")
async def hitl_pending():
    """Lista threads con HITL pendiente.

    En una implementación real, esto consultaría una cola persistente.
    Por ahora, devolvemos info básica — el frontend maneja los thread_ids.
    """
    return {
        "message": "Los threads pendientes se identifican cuando /chat devuelve requires_hitl=true",
        "note": "Usa POST /hitl/{thread_id}/approve o /hitl/{thread_id}/reject para resolver",
    }


@app.post("/hitl/{thread_id}/approve")
async def hitl_approve(thread_id: str):
    """Aprueba una acción pausada en HITL."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = _graph.invoke(Command(resume="approve"), config=config)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread no encontrado o ya resuelto: {e}")

    return {
        "thread_id": thread_id,
        "decision": "approved",
        "respuesta": result.get("respuesta", ""),
        "confidence": result.get("confidence", 0.0),
    }


@app.post("/hitl/{thread_id}/reject")
async def hitl_reject(thread_id: str):
    """Rechaza una acción pausada en HITL."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = _graph.invoke(Command(resume="reject"), config=config)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread no encontrado o ya resuelto: {e}")

    return {
        "thread_id": thread_id,
        "decision": "rejected",
        "respuesta": result.get("respuesta", ""),
    }


@app.get("/stats")
async def stats():
    """Devuelve estadísticas de tracing."""
    return get_stats()
