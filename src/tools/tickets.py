"""Herramientas de tickets de soporte.

Fase 7 (REL-04): las operaciones de tickets se mueven a la base de datos SQLite
compartida con data_agent, eliminando la lista global en memoria.

Fase 12: soporte opcional de Supabase para persistencia en producción.
"""

from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from src.db.supabase_client import get_supabase_client, is_supabase_configured
from src.tools.sql import _init_db

DB_PATH = Path(__file__).parent.parent.parent / "data" / "aegis.db"


def _get_connection():
    """Abre una conexion SQLite local (legacy)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _init_db()
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

    if is_supabase_configured():
        client = get_supabase_client()
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

    conn = _get_connection()
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
def listar_tickets(estado: str = "todos", created_by: str = "") -> str:
    """Lista los tickets de soporte existentes.

    Args:
        estado: Filtrar por estado: "abierto", "cerrado", o "todos" (default).
        created_by: Si se proporciona, filtra tickets creados por ese usuario.

    Returns:
        Lista de tickets formateada, o mensaje si no hay resultados.
    """
    if is_supabase_configured():
        client = get_supabase_client()
        query = client.table("tickets").select("id, titulo, prioridad, estado")
        if created_by and estado != "todos":
            response = query.eq("estado", estado).eq("created_by", created_by).order("id", desc=True).execute()
        elif created_by:
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

    conn = _get_connection()
    try:
        if created_by and estado != "todos":
            cursor = conn.execute(
                "SELECT id, titulo, prioridad, estado FROM tickets WHERE estado = ? AND created_by = ? ORDER BY id DESC",
                (estado, created_by),
            )
        elif created_by:
            cursor = conn.execute(
                "SELECT id, titulo, prioridad, estado FROM tickets WHERE created_by = ? ORDER BY id DESC",
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
def buscar_ticket(ticket_id: int) -> str:
    """Busca un ticket por su ID y muestra todos sus detalles.

    Args:
        ticket_id: ID numerico del ticket a buscar.

    Returns:
        Detalles completos del ticket, o mensaje si no existe.
    """
    if is_supabase_configured():
        client = get_supabase_client()
        response = client.table("tickets").select("*").eq("id", ticket_id).execute()
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

    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
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
