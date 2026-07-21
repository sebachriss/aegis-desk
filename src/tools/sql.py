"""Herramienta de consulta SQL de solo lectura (SELECT) sobre SQLite local o Postgres/Supabase.

Seguridad:
  - Conexion SQLite en modo solo lectura (file URI mode=ro).
  - Postgres: session read-only + validación textual idéntica.
  - set_authorizer (SQLite) denega cualquier operacion distinta de SELECT/READ.
  - Solo permite lectura de tablas en ALLOWED_TABLES.
  - Bloquea sqlite_master, sqlite_sequence, pragmas y funciones peligrosas.
  - Valida que la query sea SELECT y rechaza comentarios/stacked queries.
  - Limita filas devueltas y aplica timeout.
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from src.config import get_settings

# Base de datos SQLite simulada de Aegis Corp
DB_PATH = Path(__file__).parent.parent.parent / "data" / "aegis.db"

# Tablas permitidas — si no esta aqui, no se puede consultar
ALLOWED_TABLES = {"empleados", "tickets", "departamentos", "vacaciones_saldo", "vacaciones_solicitudes", "accesos"}

# Columnas sensibles que se redactan por defecto en los resultados
SENSITIVE_COLUMNS = {"email", "salario"}

# Maximo de filas que una query puede devolver
MAX_ROWS = 50

# Tiempo maximo de ejecucion de una query (segundos)
QUERY_TIMEOUT = 5


SQL_KEYWORDS_DENY = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "REPLACE", "MERGE",
}


def _init_db():
    """Crea la base de datos simulada con datos de ejemplo si no existe."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS departamentos (
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            presupuesto REAL
        );

        CREATE TABLE IF NOT EXISTS empleados (
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            email TEXT,
            departamento_id INTEGER,
            salario REAL,
            FOREIGN KEY (departamento_id) REFERENCES departamentos(id)
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            prioridad TEXT,
            estado TEXT,
            empleado_id INTEGER,
            created_by TEXT,
            created_at TEXT,
            FOREIGN KEY (empleado_id) REFERENCES empleados(id)
        );

        CREATE TABLE IF NOT EXISTS vacaciones_saldo (
            id INTEGER PRIMARY KEY,
            empleado_email TEXT UNIQUE,
            dias_totales INTEGER DEFAULT 22,
            dias_usados INTEGER DEFAULT 0,
            anio INTEGER
        );

        CREATE TABLE IF NOT EXISTS vacaciones_solicitudes (
            id INTEGER PRIMARY KEY,
            solicitante TEXT,
            fecha_inicio TEXT,
            fecha_fin TEXT,
            dias INTEGER,
            estado TEXT,
            aprobado_por TEXT,
            created_at TEXT,
            motivo TEXT,
            idempotency_key TEXT
        );

        CREATE TABLE IF NOT EXISTS accesos (
            id INTEGER PRIMARY KEY,
            email TEXT,
            sistema TEXT,
            estado TEXT,
            otorgado_por TEXT,
            created_at TEXT
        );
    """)

    # Intentar anadir columnas de migracion si la tabla existe sin ellas
    for col in ("descripcion", "created_by", "created_at"):
        try:
            cursor.execute(f"ALTER TABLE tickets ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass

    # Insertar datos de ejemplo solo si las tablas estan vacias
    cursor.execute("SELECT COUNT(*) FROM departamentos")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO departamentos (nombre, presupuesto) VALUES (?, ?)",
            [("IT", 500000), ("RRHH", 200000), ("Ventas", 800000), ("Finanzas", 300000)],
        )

    cursor.execute("SELECT COUNT(*) FROM empleados")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO empleados (nombre, email, departamento_id, salario) VALUES (?, ?, ?, ?)",
            [
                ("Ana Garcia", "ana@aegiscorp.com", 1, 75000),
                ("Luis Perez", "luis@aegiscorp.com", 1, 68000),
                ("Maria Lopez", "maria@aegiscorp.com", 2, 60000),
                ("Carlos Ruiz", "carlos@aegiscorp.com", 3, 85000),
                ("Elena Diaz", "elena@aegiscorp.com", 3, 72000),
                ("Javier Torres", "javier@aegiscorp.com", 4, 90000),
            ],
        )

    cursor.execute("SELECT COUNT(*) FROM tickets")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO tickets (titulo, prioridad, estado, empleado_id, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("VPN no conecta", "media", "abierto", 1, "system", "2026-07-16T00:00:00"),
                ("Laptop lenta", "baja", "abierto", 2, "system", "2026-07-16T00:00:00"),
                ("Email no llega", "alta", "cerrado", 1, "system", "2026-07-16T00:00:00"),
                ("Solicitud de monitor", "baja", "abierto", 3, "system", "2026-07-16T00:00:00"),
            ],
        )

    anio_actual = datetime.now().year
    cursor.execute("SELECT COUNT(*) FROM vacaciones_saldo")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO vacaciones_saldo (empleado_email, dias_totales, dias_usados, anio) VALUES (?, ?, ?, ?)",
            [
                ("ana@aegiscorp.com", 22, 0, anio_actual),
                ("luis@aegiscorp.com", 22, 0, anio_actual),
                ("maria@aegiscorp.com", 22, 0, anio_actual),
                ("carlos@aegiscorp.com", 22, 0, anio_actual),
                ("elena@aegiscorp.com", 22, 0, anio_actual),
                ("javier@aegiscorp.com", 22, 0, anio_actual),
            ],
        )

    conn.commit()
    conn.close()


def _has_limit_clause(query: str) -> bool:
    """Detecta si una query ya tiene una clausula LIMIT final."""
    # Buscar LIMIT al final, ignorando comentarios simples
    no_comments = re.sub(r"--[^\n]*", "", query)
    return bool(re.search(r"\bLIMIT\s+\d+\s*($|;)", no_comments, flags=re.IGNORECASE))


def _strip_sql_comments(query: str) -> str:
    """Elimina comentarios SQL de una query.

    No es un parser completo, pero elimina patrones simples de -- y /* */.
    """
    query = re.sub(r"/\*.*?\*/", "", query, flags=re.DOTALL)
    query = re.sub(r"--[^\n]*", "", query)
    return query


def _validate_select(query: str) -> str | None:
    """Valida que la query sea un SELECT y no contenga palabras peligrosas.

    Returns:
        Mensaje de error si no es valida, None si es valida.
    """
    cleaned = _strip_sql_comments(query).strip()
    if not cleaned:
        return "Error: La consulta esta vacia o solo contiene comentarios."

    # Permitir punto y coma final (terminador), pero rechazar ; interno
    cleaned = cleaned.rstrip(";")
    if ";" in cleaned:
        return "Error: No se permiten múltiples sentencias SQL."

    first_word = re.split(r"\s+", cleaned, maxsplit=1)[0].upper()
    if first_word != "SELECT":
        return f"Error: Solo se permiten consultas SELECT. Palabra inicial: {first_word}"

    upper = cleaned.upper()
    for keyword in SQL_KEYWORDS_DENY:
        if re.search(rf"\b{keyword}\b", upper):
            return f"Error: '{keyword}' no esta permitido. Solo SELECT."

    return None


def _authorizer(action: int, arg1: str | None, arg2: str | None, dbname: str, trigger: str) -> int:
    """Callback de autorizacion de SQLite.

    Permite:
      - SQLITE_SELECT (inicio de SELECT)
      - SQLITE_READ sobre tablas en ALLOWED_TABLES
    Deniega todo lo demas.
    """
    # Permitir la operacion SELECT en si misma
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK

    # Permitir lectura de columnas solo de tablas permitidas
    if action == sqlite3.SQLITE_READ:
        table = arg1
        if table in ALLOWED_TABLES:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    # Denegar funciones no aprobadas y acceso a sqlite_master/sequence
    # Las funciones de lectura no modifican datos, pero las restringimos a un allowlist.
    if action == sqlite3.SQLITE_FUNCTION:
        # arg2 contiene el nombre de la funcion; arg1 es argumento/columna
        func_name = (arg2 or arg1 or "").upper()
        allowed = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "LENGTH", "UPPER", "LOWER"}
        if func_name in allowed or func_name.endswith(")"):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    if action in (
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_ANALYZE,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_REINDEX,
    ):
        return sqlite3.SQLITE_DENY

    # Por defecto permitir operaciones de lectura inocuas (ej. SQLITE_ROW)
    if action == sqlite3.SQLITE_ROW:
        return sqlite3.SQLITE_OK

    return sqlite3.SQLITE_DENY


def _is_sensitive(column: str) -> bool:
    return column.lower() in SENSITIVE_COLUMNS


def _format_rows(rows: list, columns: list[str], mask_sensitive: bool = True) -> str:
    """Formatea filas como tabla, redactando columnas sensibles si aplica."""
    display_columns = columns
    display_rows = []
    for row in rows:
        new_row = []
        for col, val in zip(columns, row):
            if mask_sensitive and _is_sensitive(col):
                new_row.append("***")
            else:
                new_row.append(str(val) if val is not None else "NULL")
        display_rows.append(new_row)

    header = " | ".join(display_columns)
    separator = "-+-".join("-" * len(c) for c in display_columns)
    lines = [header, separator]
    for row in display_rows:
        lines.append(" | ".join(row))

    return f"Resultados ({len(rows)} filas):\n" + "\n".join(lines)


def _execute_postgres(query: str) -> str:
    """Ejecuta un SELECT validado contra Postgres/Supabase en modo solo lectura."""
    from src.db.postgres_utils import get_postgres_connection

    try:
        conn = get_postgres_connection(read_only=True, connect_timeout=QUERY_TIMEOUT)
    except Exception as e:
        return f"Error de conexion: {e}"

    try:
        with conn.cursor() as cursor:
            # Validación textual idéntica a SQLite
            error = _validate_select(query)
            if error:
                return error

            limited_query = query.strip().rstrip(";")
            if not _has_limit_clause(limited_query):
                limited_query = f"{limited_query} LIMIT {MAX_ROWS + 1}"

            cursor.execute(limited_query)
            rows = cursor.fetchmany(MAX_ROWS + 1)
            columns = [desc[0] for desc in cursor.description or []]

            if not rows:
                return "La consulta no devolvio resultados."

            truncated = len(rows) > MAX_ROWS
            rows = rows[:MAX_ROWS]
            result = _format_rows(rows, columns, mask_sensitive=True)
            if truncated:
                result += f"\n... (limite de {MAX_ROWS} filas alcanzado)"
            return result
    except Exception as e:
        return f"Error de SQL: {e}"
    finally:
        conn.close()


def consultar_sql(query: str) -> str:
    """Ejecuta una consulta SQL de solo lectura (SELECT) sobre la base de datos de Aegis Corp.

    Tablas disponibles:
      - empleados (id, nombre, email, departamento_id, salario)
      - departamentos (id, nombre, presupuesto)
      - tickets (id, titulo, prioridad, estado, empleado_id)

    Args:
        query: Consulta SQL SELECT. Solo se permite SELECT.

    Returns:
        Resultados de la consulta formateados, o mensaje de error si la query es invalida.
    """
    settings = get_settings()

    # Si hay DATABASE_URL, usar Postgres/Supabase en modo solo lectura
    if settings.database_url:
        return _execute_postgres(query)

    # Asegurar que la DB local existe (solo la primera vez)
    _init_db()

    # 1. Validacion textual rapida
    error = _validate_select(query)
    if error:
        return error

    # 2. Abrir conexion en modo SOLO LECTURA
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT)
    try:
        conn.set_authorizer(_authorizer)
        cursor = conn.cursor()

        # 3. Ejecutar con LIMIT automatico para evitar tablas grandes
        limited_query = query.strip().rstrip(";")
        # Evitar LIMIT duplicado si la query ya lo incluye
        if not _has_limit_clause(limited_query):
            limited_query = f"{limited_query} LIMIT {MAX_ROWS + 1}"

        cursor.execute(limited_query)
        rows = cursor.fetchmany(MAX_ROWS + 1)
        columns = [desc[0] for desc in cursor.description or []]

        if not rows:
            return "La consulta no devolvio resultados."

        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]

        result = _format_rows(rows, columns, mask_sensitive=True)
        if truncated:
            result += f"\n... (limite de {MAX_ROWS} filas alcanzado)"

        return result
    except sqlite3.Error as e:
        return f"Error de SQL: {e}"
    finally:
        conn.close()


consultar_sql_tool = tool(consultar_sql)
# `consultar_sql` sigue siendo la función callable; `consultar_sql_tool` es el StructuredTool para agentes.
