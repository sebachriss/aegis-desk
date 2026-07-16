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
HITL usa SqliteSaver como checkpointer y una cola persistente en SQLite.
"""

import json
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite import SqliteSaver
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

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT_DB_PATH = DATA_DIR / "checkpoints.sqlite"
HITL_DB_PATH = DATA_DIR / "hitl_queue.sqlite"

_checkpointer = SqliteSaver(sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False))
_graph = build_graph(checkpointer=_checkpointer)

app = FastAPI(
    title="Aegis Desk API",
    description="Plataforma de soporte interno inteligente multi-agente",
    version="1.0.0",
)

# CORS restringido a los origenes configurados
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if settings.environment == "production" and not cors_origins:
    raise RuntimeError("CORS_ORIGINS es obligatorio en produccion")
if not cors_origins:
    cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# --- HITL queue helpers ---


def _get_hitl_db():
    """Conexion a la cola HITL persistente. Crea la tabla si no existe."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(HITL_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hitl_queue (
            thread_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT "pending",
            requested_by TEXT,
            role TEXT,
            tool_name TEXT,
            risk_level TEXT,
            created_at TEXT,
            approved_by TEXT,
            approved_at TEXT,
            action_plan_json TEXT
        )"""
    )
    conn.commit()
    return conn


def _enqueue_hitl(thread_id: str, action_plan: dict | None, user: dict):
    """Agrega una solicitud HITL a la cola persistente."""
    db = _get_hitl_db()
    try:
        now = datetime.now().isoformat()
        if action_plan:
            requested_by = action_plan.get("requested_by") or user.get("username")
            role = action_plan.get("role") or user.get("role")
            tool_name = action_plan.get("tool_name")
            risk_level = action_plan.get("risk_level", "unknown")
            action_plan_json = json.dumps(action_plan, ensure_ascii=False)
        else:
            requested_by = user.get("username")
            role = user.get("role")
            tool_name = None
            risk_level = None
            action_plan_json = None
        db.execute(
            """INSERT OR REPLACE INTO hitl_queue
            (thread_id, status, requested_by, role, tool_name, risk_level, created_at, approved_by, approved_at, action_plan_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (thread_id, "pending", requested_by, role, tool_name, risk_level, now, None, None, action_plan_json),
        )
        db.commit()
    finally:
        db.close()


def _update_hitl_status(thread_id: str, status: str, approved_by: str | None = None):
    """Actualiza el estado de una entrada HITL."""
    db = _get_hitl_db()
    try:
        approved_at = datetime.now().isoformat() if status in ("approved", "rejected") and approved_by else None
        db.execute(
            "UPDATE hitl_queue SET status = ?, approved_by = ?, approved_at = ? WHERE thread_id = ?",
            (status, approved_by, approved_at, thread_id),
        )
        db.commit()
    finally:
        db.close()


def _get_pending_hitl() -> list[dict]:
    """Devuelve la lista de entradas HITL con estado pending."""
    db = _get_hitl_db()
    try:
        rows = db.execute(
            "SELECT * FROM hitl_queue WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def _validate_hitl_thread(thread_id: str):
    """Valida que un thread este pausado en HITL con una accion pendiente.

    Lanza HTTPException 404 si no existe o no esta en HITL,
    409 si no hay una accion con approval_status == "pending".
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = _graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail="Thread no encontrado")

    if state is None or not getattr(state, "metadata", None):
        raise HTTPException(status_code=404, detail="Thread no encontrado")

    if "hitl_review" not in state.next:
        raise HTTPException(status_code=409, detail="El thread no esta pausado en HITL")

    action_plan = state.values.get("action_plan") if state.values else None
    if not action_plan or action_plan.get("approval_status") != "pending":
        raise HTTPException(
            status_code=409, detail="No hay una accion pendiente de aprobacion en este thread"
        )


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
    """Health check: SQLite, cola HITL, checkpointer y API keys."""
    checks = {}

    # SQLite/checkpointer
    try:
        _checkpointer.conn.execute("SELECT 1").fetchone()
        checks["checkpointer"] = "ok"
    except Exception as exc:
        checks["checkpointer"] = f"error: {exc}"

    # Base de checkpoints como archivo SQLite
    try:
        conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks["sqlite"] = "ok"
    except Exception as exc:
        checks["sqlite"] = f"error: {exc}"

    # Cola HITL
    try:
        db = _get_hitl_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        checks["hitl_queue"] = "ok"
    except Exception as exc:
        checks["hitl_queue"] = f"error: {exc}"

    # API keys
    api_keys = {
        "deepinfra_api_key": bool(settings.deepinfra_api_key),
        "groq_api_key": bool(settings.groq_api_key),
    }

    all_ok = all(v == "ok" for v in checks.values()) and all(api_keys.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "service": "aegis-desk",
        "langsmith_tracing": _langsmith_enabled,
        "checks": checks,
        "api_keys": api_keys,
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
        raise HTTPException(
            status_code=429,
            detail=rate["reason"],
            headers={"Retry-After": str(rate["retry_after"])},
        )

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
        # Persistir la solicitud en la cola HITL
        _enqueue_hitl(thread_id, result.get("action_plan"), user)
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

    Consulta la cola persistente SQLite.
    """
    return _get_pending_hitl()


@app.post("/hitl/{thread_id}/approve")
async def hitl_approve(thread_id: str, user: dict = Depends(require_admin)):
    """Aprueba una accion pausada en HITL. Requiere rol admin."""
    _validate_hitl_thread(thread_id)

    _update_hitl_status(thread_id, "approved", approved_by=user.get("username"))

    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = _graph.invoke(Command(resume="approve"), config=config)
    except Exception:
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
    _validate_hitl_thread(thread_id)

    _update_hitl_status(thread_id, "rejected", approved_by=user.get("username"))

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
