"""FastAPI app para Aegis Desk.

Endpoints:
  POST /login         — autenticar usuario y obtener JWT token
  POST /chat          — enviar mensaje (requiere auth)
  GET  /hitl/pending  — listar threads con HITL pendiente (admin)
  POST /hitl/{thread_id}/approve — aprobar accion pendiente (admin)
  POST /hitl/{thread_id}/reject  — rechazar accion pendiente (admin)
  GET  /stats         — estadisticas de tracing (admin)
  GET  /health        — health check
  GET  /me            — info del usuario autenticado

Auth: JWT token en header Authorization: Bearer <token>
HITL usa MemorySaver checkpointer con thread_id por conversacion.
"""

import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agents.graph import build_graph
from src.auth.jwt_handler import create_access_token, get_current_user, verify_token
from src.auth.users import authenticate, get_user
from src.config import get_settings
from src.observability.langsmith import setup_langsmith_tracing
from src.observability.tracing import get_stats, trace_execution
from src.security.pii_filter import filter_pii
from src.security.rbac import validate_role
from src.security.rate_limiter import check_login_rate_limit

# Habilitar LangSmith tracing si hay API key configurada
_langsmith_enabled = setup_langsmith_tracing()

# --- Setup ---

settings = get_settings()

app = FastAPI(
    title="Aegis Desk API",
    description="Plataforma de soporte interno inteligente multi-agente",
    version="1.0.0",
)

# CORS restringido a los origenes configurados
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if not cors_origins:
    cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Checkpointer compartido para HITL (persiste entre requests en memoria)
_checkpointer = MemorySaver()
_graph = build_graph(checkpointer=_checkpointer)


# --- Schemas ---

class ChatRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Mensaje del usuario",
    )


class ChatResponse(BaseModel):
    thread_id: str
    intencion: str
    respuesta: str
    confidence: float
    fuentes: list[dict]
    elapsed_seconds: float
    requires_hitl: bool


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)


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

    Raises HTTPException 401 si no hay token o es invalido.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta token de autenticacion")

    token = authorization.split(" ", 1)[1]
    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Token invalido o expirado")

    return user


async def require_admin(user: dict = Depends(get_auth_user)) -> dict:
    """Dependency que requiere rol admin."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    return user


# --- Exception handlers ---


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Evita fugas de detalles internos en respuestas de error."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """No expone stack traces ni configuracion sensible."""
    # En produccion loggear el error internamente, no devolverlo
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor"},
    )


# --- Endpoints ---


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "aegis-desk",
        "langsmith_tracing": _langsmith_enabled,
    }


@app.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    """Autentica un usuario y devuelve un JWT token.

    Aplica rate limiting por IP para prevenir fuerza bruta.
    No revela si el usuario existe.
    """
    client_ip = request.client.host if request.client else "unknown"
    rate = check_login_rate_limit(client_ip)
    if not rate["allowed"]:
        raise HTTPException(status_code=429, detail=rate["reason"])

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
    """Envia un mensaje al agente y devuelve la respuesta.

    Requiere autenticacion JWT. El rol se extrae del token, no del request.
    Si el grafo se pausa en HITL, devuelve requires_hitl=True
    y el thread_id para aprobar/rechazar despues.
    """
    user_id = user["username"]
    role = user["role"]

    # Validar rol conocido antes de procesar (fail closed)
    if not validate_role(role):
        raise HTTPException(status_code=403, detail="Rol invalido")

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
        "tool_name": None,
        "authorization_decision": None,
        "action_plan": None,
        "approved_by": None,
        "approved_at": None,
    }, config=config)
    elapsed = time.time() - start

    # Verificar si se pauso en HITL
    is_interrupted = bool(result.get("__interrupt__"))

    if is_interrupted:
        return ChatResponse(
            thread_id=thread_id,
            intencion=result.get("intencion", ""),
            respuesta="⏸️ Tu solicitud requiere aprobacion humana. Pendiente de revision.",
            confidence=result.get("confidence", 0.0),
            fuentes=result.get("fuentes", []),
            elapsed_seconds=round(elapsed, 2),
            requires_hitl=True,
        )

    # Aplicar filtro PII antes de exponer o guardar la respuesta
    raw_respuesta = result.get("respuesta", "")
    respuesta_filtrada, _ = filter_pii(raw_respuesta)

    # Registrar trace con datos redactados
    trace_execution(
        query=req.query,
        intencion=result.get("intencion", ""),
        respuesta=respuesta_filtrada[:500],
        confidence=result.get("confidence", 0.0),
        fuentes=result.get("fuentes", []),
        retries=result.get("retries", 0),
        elapsed_seconds=elapsed,
        user_id=user_id,
        role=role,
        tool_name=result.get("tool_name"),
        authorization_decision=result.get("authorization_decision"),
        action_plan=result.get("action_plan"),
        approved_by=result.get("approved_by"),
        approved_at=result.get("approved_at"),
    )

    return ChatResponse(
        thread_id=thread_id,
        intencion=result.get("intencion", ""),
        respuesta=respuesta_filtrada,
        confidence=result.get("confidence", 0.0),
        fuentes=result.get("fuentes", []),
        elapsed_seconds=round(elapsed, 2),
        requires_hitl=False,
    )


@app.get("/hitl/pending")
async def hitl_pending(user: dict = Depends(require_admin)):
    """Lista threads con HITL pendiente (solo admin).

    En una implementacion real, esto consultaria una cola persistente.
    Por ahora, devolvemos info basica.
    """
    return {
        "message": "Los threads pendientes se identifican cuando /chat devuelve requires_hitl=true",
        "note": "Usa POST /hitl/{thread_id}/approve o /hitl/{thread_id}/reject para resolver",
    }


@app.post("/hitl/{thread_id}/approve")
async def hitl_approve(thread_id: str, user: dict = Depends(require_admin)):
    """Aprueba una accion pausada en HITL. Requiere rol admin."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = _graph.invoke(Command(resume="approve"), config=config)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Thread no encontrado o ya resuelto")

    return {
        "thread_id": thread_id,
        "decision": "approved",
        "respuesta": result.get("respuesta", ""),
        "confidence": result.get("confidence", 0.0),
    }


@app.post("/hitl/{thread_id}/reject")
async def hitl_reject(thread_id: str, user: dict = Depends(require_admin)):
    """Rechaza una accion pausada en HITL. Requiere rol admin."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = _graph.invoke(Command(resume="reject"), config=config)
    except Exception:
        raise HTTPException(status_code=404, detail="Thread no encontrado o ya resuelto")

    return {
        "thread_id": thread_id,
        "decision": "rejected",
        "respuesta": result.get("respuesta", ""),
    }


@app.get("/stats")
async def stats(user: dict = Depends(require_admin)):
    """Devuelve estadisticas de tracing (solo admin)."""
    return get_stats()
