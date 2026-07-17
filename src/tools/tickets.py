"""Herramientas de tickets de soporte.

Fase 7 (REL-04): las operaciones de tickets se mueven a una base de datos
compartida con data_agent. El backend preferido es PostgreSQL (via DATABASE_URL);
Si no esta configurado, se usa Supabase (REST) si hay credenciales; de lo contrario
SQLite local como fallback.
"""

from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from src.config import get_settings
from src.db.postgres_utils import get_postgres_connection
from src.db.supabase_client import get_supabase_service_client, is_supabase_configured

DB_PATH = Path(__file__).parent.parent.parent / "data" / "aegis.db"


def _use_postgres() -> bool:
    """Devuelve True si hay una DATABASE_URL configurada."""
    settings = get_settings()
    return bool(settings.database_url)


def _init_sqlite():
    """Crea la base de datos simulada con datos de ejemplo si no existe."""
    from src.tools.sql import _init_db

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _init_db()


def _get_sqlite_connection():
    """Abre una conexion SQLite local (legacy)."""
    _init_sqlite()
    import sqlite3

    return sqlite3.connect(str(DB_PATH))


@tool
def crear_ticket(titulo: str, descripcion: str, prioridad: str, created_by: str = "") -> str:
    """Crea un nuevo ticket de soporte en el sistema.

    Args:
        titulo: Resumen corto del problema (max 100 caracteres).
        descripcion: Detalle del problema reportado.
        prioridad: Nivel de urgencia: "baja", "media" o "alta".
        created_by: Usuario que crea el ticket (inyectado por el executor).

    Returns:
        Confirmacion con el ID del ticket creado.
    """
    if prioridad not in ("baja", "media", "alta"):
        return f"Error: prioridad '{prioridad}' no valida. Usa: baja, media, o alta."

    if len(titulo) > 100:
        titulo = titulo[:100]

    created_at = datetime.now().isoformat()

    if _use_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tickets (titulo, descripcion, prioridad, estado, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (titulo, descripcion, prioridad, "abierto", created_by, created_at),
                )
                ticket_id = cur.fetchone()[0]
            conn.commit()
        return f"Ticket #{ticket_id} creado con prioridad '{prioridad}'. Titulo: {titulo}. Estado: abierto. Creado por: {created_by or 'sistema'}."

    if is_supabase_configured():
        client = get_supabase_service_client()
        data = {
            "titulo": titulo,
            "descripcion": descripcion,
            "prioridad": prioridad,
            "estado": "abierto",
            "created_by": created_by,
            "created_at": created_at,
        }
        response = client.table("tickets").insert(data).execute()
        ticket_id = response.data[0]["id"]
        return f"Ticket #{ticket_id} creado con prioridad '{prioridad}'. Titulo: {titulo}. Estado: abierto. Creado por: {created_by or 'sistema'}."

    conn = _get_sqlite_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO tickets (titulo, descripcion, prioridad, estado, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (titulo, descripcion, prioridad, "abierto", created_by, created_at),
        )
        conn.commit()
        ticket_id = cursor.lastrowid
    finally:
        conn.close()

    return f"Ticket #{ticket_id} creado con prioridad '{prioridad}'. Titulo: {titulo}. Estado: abierto. Creado por: {created_by or 'sistema'}."


@tool
def listar_tickets(estado: str = "todos", created_by: str = "", role: str = "empleado") -> str:
    """Lista los tickets de soporte existentes.

    Args:
        estado: Filtrar por estado: "abierto", "cerrado", o "todos" (default).
        created_by: Si se proporciona, filtra tickets creados por ese usuario.
        role: Rol del usuario; solo admin puede listar tickets de otros.

    Returns:
        Lista de tickets formateada, o mensaje si no hay resultados.
    """
    is_admin = role == "admin"
    if not is_admin and not created_by:
        return "Error: un empleado debe especificar su usuario para listar tickets."

    if _use_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                params: list = []
                where_clauses: list = []
                # Los empleados ven sus propios tickets y los tickets del sistema
                owner_filter = "(created_by = %s OR created_by = 'system')" if created_by and role != "admin" else "created_by = %s" if created_by else None
                if created_by and estado != "todos":
                    if role != "admin":
                        where_clauses.append(f"estado = %s AND {owner_filter}")
                        params.extend([estado, created_by])
                    else:
                        where_clauses.append("estado = %s AND created_by = %s")
                        params.extend([estado, created_by])
                elif created_by:
                    if role != "admin":
                        where_clauses.append(owner_filter)
                        params.append(created_by)
                    else:
                        where_clauses.append("created_by = %s")
                        params.append(created_by)
                elif estado != "todos":
                    if estado not in ("abierto", "cerrado"):
                        return f"Error: estado '{estado}' no valido. Usa: abierto, cerrado, o todos."
                    where_clauses.append("estado = %s")
                    params.append(estado)

                sql = "SELECT id, titulo, prioridad, estado FROM tickets"
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)
                sql += " ORDER BY id DESC"

                cur.execute(sql, params)
                tickets = cur.fetchall()

        if not tickets:
            return f"No hay tickets con estado '{estado}'."
        lineas = [f"#{t[0]} [{t[2]}] {t[1]} - {t[3]}" for t in tickets]
        return f"Tickets ({len(tickets)}):\n" + "\n".join(lineas)

    if is_supabase_configured():
        client = get_supabase_service_client()
        query = client.table("tickets").select("id, titulo, prioridad, estado")
        if created_by and estado != "todos":
            if role != "admin":
                response = query.eq("estado", estado).or_(f"created_by.eq.{created_by},created_by.eq.system").order("id", desc=True).execute()
            else:
                response = query.eq("estado", estado).eq("created_by", created_by).order("id", desc=True).execute()
        elif created_by:
            if role != "admin":
                response = query.or_(f"created_by.eq.{created_by},created_by.eq.system").order("id", desc=True).execute()
            else:
                response = query.eq("created_by", created_by).order("id", desc=True).execute()
        elif estado == "todos":
            response = query.order("id", desc=True).execute()
        else:
            if estado not in ("abierto", "cerrado"):
                return f"Error: estado '{estado}' no valido. Usa: abierto, cerrado, o todos."
            response = query.eq("estado", estado).order("id", desc=True).execute()
        tickets = response.data
        if not tickets:
            return f"No hay tickets con estado '{estado}'."
        lineas = [f"#{t['id']} [{t['prioridad']}] {t['titulo']} - {t['estado']}" for t in tickets]
        return f"Tickets ({len(tickets)}):\n" + "\n".join(lineas)

    conn = _get_sqlite_connection()
    try:
        empleado_filter = "(created_by = ? OR created_by = 'system')" if role != "admin" else "created_by = ?"
        if created_by and estado != "todos":
            cursor = conn.execute(
                f"SELECT id, titulo, prioridad, estado FROM tickets WHERE estado = ? AND {empleado_filter} ORDER BY id DESC",
                (estado, created_by),
            )
        elif created_by:
            cursor = conn.execute(
                f"SELECT id, titulo, prioridad, estado FROM tickets WHERE {empleado_filter} ORDER BY id DESC",
                (created_by,),
            )
        elif estado == "todos":
            cursor = conn.execute("SELECT id, titulo, prioridad, estado FROM tickets ORDER BY id DESC")
        else:
            if estado not in ("abierto", "cerrado"):
                return f"Error: estado '{estado}' no valido. Usa: abierto, cerrado, o todos."
            cursor = conn.execute(
                "SELECT id, titulo, prioridad, estado FROM tickets WHERE estado = ? ORDER BY id DESC",
                (estado,),
            )
        tickets = cursor.fetchall()
    finally:
        conn.close()

    if not tickets:
        return f"No hay tickets con estado '{estado}'."

    lineas = [f"#{t[0]} [{t[2]}] {t[1]} - {t[3]}" for t in tickets]
    return f"Tickets ({len(tickets)}):\n" + "\n".join(lineas)


@tool
def buscar_ticket(ticket_id: int, created_by: str = "", role: str = "empleado") -> str:
    """Busca un ticket por su ID y muestra todos sus detalles.

    Args:
        ticket_id: ID numerico del ticket a buscar.
        created_by: Usuario que creo el ticket (inyectado por el executor).
        role: Rol del usuario; solo admin puede buscar tickets ajenos.

    Returns:
        Detalles completos del ticket, o mensaje si no existe.
    """
    is_admin = role == "admin"
    if not is_admin and not created_by:
        return "Error: un empleado debe especificar su usuario para buscar un ticket."

    if _use_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                if is_admin:
                    cur.execute("SELECT id, titulo, descripcion, prioridad, estado FROM tickets WHERE id = %s", (ticket_id,))
                else:
                    cur.execute(
                        "SELECT id, titulo, descripcion, prioridad, estado FROM tickets WHERE id = %s AND (created_by = %s OR created_by = 'system')",
                        (ticket_id, created_by),
                    )
                t = cur.fetchone()

        if not t:
            return f"No se encontro el ticket #{ticket_id}."
        return (
            f"Ticket #{t[0]}\n"
            f"  Titulo: {t[1]}\n"
            f"  Descripcion: {t[2]}\n"
            f"  Prioridad: {t[3]}\n"
            f"  Estado: {t[4]}"
        )

    if is_supabase_configured():
        client = get_supabase_service_client()
        query = client.table("tickets").select("*").eq("id", ticket_id)
        if not is_admin:
            query = query.or_(f"created_by.eq.{created_by},created_by.eq.system")
        response = query.execute()
        t = response.data[0] if response.data else None
        if not t:
            return f"No se encontro el ticket #{ticket_id}."
        return (
            f"Ticket #{t['id']}\n"
            f"  Titulo: {t['titulo']}\n"
            f"  Descripcion: {t.get('descripcion', '')}\n"
            f"  Prioridad: {t['prioridad']}\n"
            f"  Estado: {t['estado']}"
        )

    conn = _get_sqlite_connection()
    try:
        if is_admin:
            cursor = conn.execute("SELECT id, titulo, descripcion, prioridad, estado FROM tickets WHERE id = ?", (ticket_id,))
        else:
            cursor = conn.execute(
                "SELECT id, titulo, descripcion, prioridad, estado FROM tickets WHERE id = ? AND (created_by = ? OR created_by = 'system')",
                (ticket_id, created_by),
            )
        t = cursor.fetchone()
    finally:
        conn.close()

    if not t:
        return f"No se encontro el ticket #{ticket_id}."

    return (
        f"Ticket #{t[0]}\n"
        f"  Titulo: {t[1]}\n"
        f"  Descripcion: {t[2]}\n"
        f"  Prioridad: {t[3]}\n"
        f"  Estado: {t[4]}"
    )
