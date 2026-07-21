"""Herramienta para crear accesos a sistemas corporativos para empleados nuevos.

Triple backend (Postgres -> Supabase REST -> SQLite), mismo patrón que tickets.py.
La tabla `accesos` guarda: email, sistema, estado, otorgado_por, created_at.
"""

from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from src.config import get_settings
from src.db.postgres_utils import get_postgres_connection
from src.db.supabase_client import get_supabase_service_client, is_supabase_configured

DB_PATH = Path(__file__).parent.parent.parent / "data" / "aegis.db"

VALID_SYSTEMS = {"email", "vpn", "slack", "github", "erp"}
VALID_DOMAINS = {"aegiscorp.com", "aegis.com"}


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


def _ensure_sqlite_table():
    """Crea la tabla accesos en SQLite si no existe."""
    conn = _get_sqlite_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accesos (
                id INTEGER PRIMARY KEY,
                email TEXT,
                sistema TEXT,
                estado TEXT,
                otorgado_por TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@tool
def crear_accesos(email: str, sistemas: list[str], created_by: str = "", role: str = "empleado") -> str:
    """Crea accesos a sistemas corporativos para un empleado nuevo.

    Args:
        email: Email corporativo del empleado (dominio aegiscorp.com o aegis.com).
        sistemas: Lista de sistemas a activar: email, vpn, slack, github, erp.
        created_by: Usuario admin que otorga el acceso (inyectado por el executor).
        role: Rol del usuario (solo admin puede crear accesos).

    Returns:
        Confirmación con los sistemas activados.
    """
    if role != "admin":
        return "Error: solo los administradores pueden crear accesos."

    if "@" not in email:
        return f"Error: email '{email}' inválido."

    domain = email.split("@")[-1].lower().strip(">")
    if domain not in VALID_DOMAINS:
        return (
            f"Error: dominio '{domain}' no permitido. "
            f"Solo se permiten dominios corporativos: {', '.join(VALID_DOMAINS)}."
        )

    sistemas = list(sistemas)
    invalid = [s for s in sistemas if s not in VALID_SYSTEMS]
    if invalid:
        return (
            f"Error: sistemas no válidos: {invalid}. "
            f"Sistemas permitidos: {', '.join(sorted(VALID_SYSTEMS))}."
        )

    created_at = datetime.now().isoformat()
    estado = "activo"

    if _use_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS accesos (
                        id SERIAL PRIMARY KEY,
                        email TEXT,
                        sistema TEXT,
                        estado TEXT,
                        otorgado_por TEXT,
                        created_at TEXT
                    )
                    """
                )
                for sistema in sistemas:
                    cur.execute(
                        """
                        INSERT INTO accesos (email, sistema, estado, otorgado_por, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (email, sistema, estado, created_by, created_at),
                    )
            conn.commit()
        return f"Accesos creados para {email}: {', '.join(sistemas)}."

    if is_supabase_configured():
        client = get_supabase_service_client()
        rows = [
            {
                "email": email,
                "sistema": sistema,
                "estado": estado,
                "otorgado_por": created_by,
                "created_at": created_at,
            }
            for sistema in sistemas
        ]
        client.table("accesos").insert(rows).execute()
        return f"Accesos creados para {email}: {', '.join(sistemas)}."

    _ensure_sqlite_table()
    conn = _get_sqlite_connection()
    try:
        cursor = conn.cursor()
        for sistema in sistemas:
            cursor.execute(
                """
                INSERT INTO accesos (email, sistema, estado, otorgado_por, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email, sistema, estado, created_by, created_at),
            )
        conn.commit()
        last_id = cursor.lastrowid
    finally:
        conn.close()

    return f"Accesos creados para {email}: {', '.join(sistemas)}."
