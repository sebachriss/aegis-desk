"""Crea tablas, extensiones y datos de ejemplo en Postgres/Supabase.

Uso:
    python scripts/migrate_postgres.py

Requiere DATABASE_URL en el entorno (.env).
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

try:
    import psycopg
except ImportError as exc:
    print("Error: instala psycopg[binary]: pip install 'psycopg[binary]>=3.0.0'")
    sys.exit(1)

from src.db.postgres_utils import normalize_database_url, get_postgres_connection
from src.rag.embeddings import get_embedding_dimension


def _enable_rls(cur):
    """Habilita Row Level Security en todas las tablas del schema public."""
    cur.execute("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename NOT LIKE 'pg_%'
          AND tablename NOT LIKE 'sql_%'
    """)
    for (table,) in cur.fetchall():
        cur.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def _enable_vector(cur):
    """Habilita la extension pgvector en el schema extensions (best practice de Supabase)."""
    try:
        cur.execute("CREATE SCHEMA IF NOT EXISTS extensions")
        # Crear en extensions; si ya existe en public, moverla
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_extension e
                    JOIN pg_namespace n ON e.extnamespace = n.oid
                    WHERE e.extname = 'vector' AND n.nspname = 'public'
                ) THEN
                    EXECUTE 'ALTER EXTENSION vector SET SCHEMA extensions';
                END IF;
            END $$;
        """)
    except psycopg.Error as exc:
        print(f"Advertencia: no se pudo crear/mover extension vector: {exc}")
        print("Habilitala manualmente desde Supabase: Database > Extensions > vector")


def _get_vector_dimension(cur, table: str, column: str) -> int | None:
    """Devuelve la dimensión de una columna vector, o None si no existe/no es vector."""
    cur.execute(
        """
        SELECT pg_catalog.format_type(atttypid, atttypmod)
        FROM pg_attribute
        WHERE attrelid = %s::regclass
          AND attname = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    if not row:
        return None
    type_str = row[0]
    # type_str tiene forma "extensions.vector(384)" o "vector(384)"
    if "vector(" in type_str:
        try:
            return int(type_str.split("vector(")[1].split(")")[0])
        except (ValueError, IndexError):
            pass
    return None


def _ensure_document_embeddings(cur, dim: int):
    """Crea o recrea la tabla de embeddings si la dimensión actual no coincide.

    Si cambiamos de modelo (por ejemplo de 384 a 4096 dims), los vectores
    antiguos son inválidos, así que es más seguro recrear la tabla.
    """
    existing_dim = _get_vector_dimension(cur, "document_embeddings", "embedding")
    if existing_dim is not None and existing_dim != dim:
        print(f"  Dimensión actual del vector: {existing_dim}. Necesaria: {dim}. Recreando tabla document_embeddings.")
        cur.execute("DROP TABLE IF EXISTS document_embeddings CASCADE")

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS document_embeddings (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source TEXT,
            metadata JSONB,
            embedding vector({dim})
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_embeddings_embedding
        ON document_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def main() -> None:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL")
    if not dsn:
        print("Error: define DATABASE_URL o SUPABASE_DATABASE_URL")
        sys.exit(1)

    conn = get_postgres_connection(dsn)
    try:
        with conn.cursor() as cur:
            _enable_vector(cur)

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS departamentos (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    presupuesto REAL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS empleados (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    email TEXT,
                    departamento_id INTEGER,
                    salario REAL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    descripcion TEXT,
                    prioridad TEXT,
                    estado TEXT,
                    empleado_id INTEGER,
                    created_by TEXT,
                    created_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vacaciones_saldo (
                    id SERIAL PRIMARY KEY,
                    empleado_email TEXT UNIQUE,
                    dias_totales INTEGER DEFAULT 22,
                    dias_usados INTEGER DEFAULT 0,
                    anio INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vacaciones_solicitudes (
                    id SERIAL PRIMARY KEY,
                    solicitante TEXT,
                    fecha_inicio TEXT,
                    fecha_fin TEXT,
                    dias INTEGER,
                    estado TEXT,
                    aprobado_por TEXT,
                    created_at TEXT,
                    motivo TEXT,
                    idempotency_key TEXT
                )
                """
            )
            cur.execute(
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
            embedding_dim = get_embedding_dimension()
            _ensure_document_embeddings(cur, embedding_dim)

            cur.execute("SELECT COUNT(*) FROM departamentos")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO departamentos (nombre, presupuesto) VALUES (%s, %s)",
                    [("IT", 500000), ("RRHH", 200000), ("Ventas", 800000), ("Finanzas", 300000)],
                )

            cur.execute("SELECT COUNT(*) FROM empleados")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO empleados (nombre, email, departamento_id, salario) VALUES (%s, %s, %s, %s)",
                    [
                        ("Ana Garcia", "ana@aegiscorp.com", 1, 75000),
                        ("Luis Perez", "luis@aegiscorp.com", 1, 68000),
                        ("Maria Lopez", "maria@aegiscorp.com", 2, 60000),
                        ("Carlos Ruiz", "carlos@aegiscorp.com", 3, 85000),
                        ("Elena Diaz", "elena@aegiscorp.com", 3, 72000),
                        ("Javier Torres", "javier@aegiscorp.com", 4, 90000),
                    ],
                )

            cur.execute("SELECT COUNT(*) FROM tickets")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO tickets (titulo, prioridad, estado, empleado_id, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        ("VPN no conecta", "media", "abierto", 1, "system", "2026-07-16T00:00:00"),
                        ("Laptop lenta", "baja", "abierto", 2, "system", "2026-07-16T00:00:00"),
                        ("Email no llega", "alta", "cerrado", 1, "system", "2026-07-16T00:00:00"),
                        ("Solicitud de monitor", "baja", "abierto", 3, "system", "2026-07-16T00:00:00"),
                    ],
                )

            anio_actual = datetime.now().year
            cur.execute("SELECT COUNT(*) FROM vacaciones_saldo")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO vacaciones_saldo (empleado_email, dias_totales, dias_usados, anio) VALUES (%s, %s, %s, %s)",
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
            print("Tablas base creadas.")

            # Tablas del checkpointer de LangGraph (PostgresSaver) en una conexion aparte
            # porque algunas migraciones usan CREATE INDEX CONCURRENTLY que no puede
            # correr dentro de una transaccion.
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                with psycopg.connect(normalize_database_url(dsn)) as chk_conn:
                    chk_conn.autocommit = True
                    saver = PostgresSaver(chk_conn)
                    saver.setup()
                    print("Tablas del checkpointer creadas.")
            except Exception as exc:
                print(f"Advertencia: no se pudieron crear tablas del checkpointer: {exc}")

            # Habilitar RLS en todas las tablas public
            with conn.cursor() as cur:
                _enable_rls(cur)
                conn.commit()
            print("RLS habilitado en tablas public.")

            print("Migración completada.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
