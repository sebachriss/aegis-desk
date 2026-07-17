"""Cola HITL con backend SQLite local o Supabase/Postgres.

Abstrae las operaciones de la cola para que `src.api.main` no dependa del
motor de base de datos. Se usa `DATABASE_URL` si esta configurado; si no,
SQLite local en `data/hitl_queue.sqlite`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import get_settings

HITL_DB_PATH = Path(__file__).parent.parent.parent / "data" / "hitl_queue.sqlite"


def _use_postgres() -> bool:
    settings = get_settings()
    return bool(settings.database_url or os.environ.get("DATABASE_URL"))


def _get_sqlite_db():
    HITL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(HITL_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hitl_queue (
            thread_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            query TEXT,
            intencion TEXT,
            requested_by TEXT,
            role TEXT,
            tool_name TEXT,
            risk_level TEXT,
            created_at TEXT,
            approved_by TEXT,
            approved_at TEXT,
            action_plan_json TEXT
        )
        """
    )
    # Migrar columnas nuevas en bases existentes
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(hitl_queue)")}
    for col in ("query", "intencion"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE hitl_queue ADD COLUMN {col} TEXT")
    conn.commit()
    return conn


def _with_sqlite(fn):
    conn = _get_sqlite_db()
    try:
        return fn(conn)
    finally:
        conn.close()


def _with_postgres(fn):
    from src.db.postgres_utils import get_postgres_connection
    with get_postgres_connection() as conn:
        return fn(conn)


def enqueue(
    thread_id: str,
    query: str,
    intencion: str,
    action_plan: dict | None,
    user: dict,
):
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

    values = (
        thread_id,
        "pending",
        query,
        intencion,
        requested_by,
        role,
        tool_name,
        risk_level,
        now,
        None,
        None,
        action_plan_json,
    )

    def _sqlite_exec(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO hitl_queue
            (thread_id, status, query, intencion, requested_by, role, tool_name, risk_level, created_at, approved_by, approved_at, action_plan_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        conn.commit()

    def _postgres_exec(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hitl_queue
                (thread_id, status, query, intencion, requested_by, role, tool_name, risk_level, created_at, approved_by, approved_at, action_plan_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    query = EXCLUDED.query,
                    intencion = EXCLUDED.intencion,
                    requested_by = EXCLUDED.requested_by,
                    role = EXCLUDED.role,
                    tool_name = EXCLUDED.tool_name,
                    risk_level = EXCLUDED.risk_level,
                    created_at = EXCLUDED.created_at,
                    approved_by = EXCLUDED.approved_by,
                    approved_at = EXCLUDED.approved_at,
                    action_plan_json = EXCLUDED.action_plan_json
                """,
                values,
            )
        conn.commit()

    if _use_postgres():
        _with_postgres(_postgres_exec)
    else:
        _with_sqlite(_sqlite_exec)


def update_status(thread_id: str, status: str, approved_by: str | None = None):
    approved_at = datetime.now().isoformat() if status in ("approved", "rejected") and approved_by else None

    def _sqlite_exec(conn):
        conn.execute(
            "UPDATE hitl_queue SET status = ?, approved_by = ?, approved_at = ? WHERE thread_id = ?",
            (status, approved_by, approved_at, thread_id),
        )
        conn.commit()

    def _postgres_exec(conn):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hitl_queue SET status = %s, approved_by = %s, approved_at = %s WHERE thread_id = %s",
                (status, approved_by, approved_at, thread_id),
            )
        conn.commit()

    if _use_postgres():
        _with_postgres(_postgres_exec)
    else:
        _with_sqlite(_sqlite_exec)


def get_pending() -> list[dict]:
    sql = """
        SELECT thread_id, query, intencion, requested_by, role, tool_name,
               risk_level, created_at, action_plan_json
        FROM hitl_queue
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """

    def _sqlite_exec(conn):
        rows = conn.execute(sql).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if not item.get("query") or not item.get("intencion"):
                try:
                    action_plan = json.loads(item.get("action_plan_json") or "{}")
                    item.setdefault("query", action_plan.get("query", ""))
                    item.setdefault("intencion", action_plan.get("intencion", ""))
                except json.JSONDecodeError:
                    pass
            items.append(item)
        return items

    def _postgres_exec(conn):
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description or []]
            items = []
            for row in rows:
                item = dict(zip(cols, row))
                if not item.get("query") or not item.get("intencion"):
                    try:
                        action_plan = json.loads(item.get("action_plan_json") or "{}")
                        item.setdefault("query", action_plan.get("query", ""))
                        item.setdefault("intencion", action_plan.get("intencion", ""))
                    except json.JSONDecodeError:
                        pass
                items.append(item)
            return items

    if _use_postgres():
        return _with_postgres(_postgres_exec)
    return _with_sqlite(_sqlite_exec)


def health_check(connect_timeout: int = 3) -> str:
    """Verifica que la cola HITL responde."""
    try:
        if _use_postgres():
            from src.db.postgres_utils import get_postgres_connection
            with get_postgres_connection(connect_timeout=connect_timeout) as conn:
                conn.execute("SELECT 1")
        else:
            _with_sqlite(lambda conn: conn.execute("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"
