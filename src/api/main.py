"""FastAPI app para Aegis Desk.

Endpoints:
  POST /login         — autenticar usuario y obtener JWT token
  POST /chat          — enviar mensaje (requiere auth)
  GET  /hitl/pending  — listar threads con HITL pendiente
  POST /hitl/{thread_id}/approve — aprobar acción pendiente (requiere auth admin)
  POST /hitl/{thread_id}/reject  — rechazar acción pendiente (requiere auth admin)
  GET  /stats         — estadísticas de tracing
  GET  /health        — health check
  GET  /me            — info del usuario autenticado

Auth: JWT token en header Authorization: Bearer <token>
HITL usa MemorySaver checkpointer con thread_id por conversación.
"""

import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from src.agents.graph import build_graph
from src.auth.jwt_handler import create_access_token, get_current_user, verify_token
from src.auth.users import authenticate, get_user
from src.observability.langsmith import setup_langsmith_tracing
from src.observability.tracing import get_stats, trace_execution
from src.security.rate_limiter import reset_user

# Habilitar LangSmith tracing si hay API key configurada
_langsmith_enabled = setup_langsmith_tracing()

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


class ChatResponse(BaseModel):
    thread_id: str
    intencion: str
    respuesta: str
    confidence: float
    fuentes: list[dict]
    elapsed_seconds: float
    requires_hitl: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    display_name: str


class HITLDecision(BaseModel):
    decision: str  # "approve" o "reject"


# --- Auth dependency ---


async def get_auth_user(authorization: str | None = Header(default=None)) -> dict:
    """Dependency que extrae y verifica el usuario del JWT token.

    Raises HTTPException 401 si no hay token o es inválido.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta token de autenticación")

    token = authorization.split(" ", 1)[1]
    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    return user


async def require_admin(user: dict = Depends(get_auth_user)) -> dict:
    """Dependency que requiere rol admin."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    return user


# --- Endpoints ---


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "aegis-desk",
        "langsmith_tracing": _langsmith_enabled,
    }


@app.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Autentica un usuario y devuelve un JWT token."""
    user = authenticate(req.username, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = create_access_token(user)
    return LoginResponse(
        access_token=token,
        role=user["role"],
        display_name=user["display_name"],
    )


@app.get("/me")
async def me(user: dict = Depends(get_auth_user)):
    """Devuelve info del usuario autenticado."""
    return user


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(get_auth_user)):
    """Envía un mensaje al agente y devuelve la respuesta.

    Requiere autenticación JWT. El rol se extrae del token, no del request.
    Si el grafo se pausa en HITL, devuelve requires_hitl=True
    y el thread_id para aprobar/rechazar después.
    """
    user_id = user["username"]
    role = user["role"]
    reset_user(user_id)

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    start = time.time()
    result = _graph.invoke({
        "messages": [],
        "query": req.query,
        "user_id": user_id,
        "role": role,
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
        user_id=user_id,
        role=role,
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
async def hitl_approve(thread_id: str, user: dict = Depends(require_admin)):
    """Aprueba una acción pausada en HITL. Requiere rol admin."""
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
async def hitl_reject(thread_id: str, user: dict = Depends(require_admin)):
    """Rechaza una acción pausada en HITL. Requiere rol admin."""
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
