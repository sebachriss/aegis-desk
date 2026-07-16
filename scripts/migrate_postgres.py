"""Crea tablas y datos de ejemplo en Postgres/Supabase.

Uso:
    DATABASE_URL=postgresql://... python scripts/migrate_postgres.py
"""

import os
import sys

try:
    import psycopg2
except ImportError as exc:
    print("Error: instala psycopg2-binary: pip install psycopg2-binary")
    sys.exit(1)


def main() -> None:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL")
    if not dsn:
        print("Error: define DATABASE_URL o SUPABASE_DATABASE_URL")
        sys.exit(1)

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
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

            conn.commit()
            print("Migración completada.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
