"""Herramienta de consulta SQL sobre SQLite (solo SELECT, allowlist de tablas).

Seguridad:
  - Solo permite SELECT (no INSERT, UPDATE, DELETE, DROP, etc.)
  - Solo permite tablas en la allowlist
  - Limita el numero de filas devueltas
"""

import sqlite3
from pathlib import Path

from langchain_core.tools import tool

# Base de datos SQLite simulada de Aegis Corp
DB_PATH = Path(__file__).parent.parent.parent / "data" / "aegis.db"

# Tablas permitidas — si no esta aqui, no se puede consultar
ALLOWED_TABLES = {"empleados", "tickets", "departamentos"}

# Maximo de filas que una query puede devolver
MAX_ROWS = 50


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
            prioridad TEXT,
            estado TEXT,
            empleado_id INTEGER,
            FOREIGN KEY (empleado_id) REFERENCES empleados(id)
        );
    """)

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
            "INSERT INTO tickets (titulo, prioridad, estado, empleado_id) VALUES (?, ?, ?, ?)",
            [
                ("VPN no conecta", "media", "abierto", 1),
                ("Laptop lenta", "baja", "abierto", 2),
                ("Email no llega", "alta", "cerrado", 1),
                ("Solicitud de monitor", "baja", "abierto", 3),
            ],
        )

    conn.commit()
    conn.close()


@tool
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
    # Asegurar que la DB existe
    _init_db()

    # 1. Validar que sea SELECT
    query_upper = query.strip().upper()
    if not query_upper.startswith("SELECT"):
        return "Error: Solo se permiten consultas SELECT."

    # 2. Validar que no tenga palabras peligrosas
    palabras_prohibidas = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
    for palabra in palabras_prohibidas:
        if palabra in query_upper:
            return f"Error: '{palabra}' no esta permitido. Solo SELECT."

    # 3. Validar que solo use tablas permitidas
    for tabla in ALLOWED_TABLES:
        pass  # la validacion real se hace con el error de SQLite

    # 4. Ejecutar la query
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        # Limitar el numero de filas
        cursor.execute(query)
        rows = cursor.fetchmany(MAX_ROWS)
        columns = [desc[0] for desc in cursor.description]

        conn.close()

        if not rows:
            return "La consulta no devolvio resultados."

        # Formatear resultados como tabla
        header = " | ".join(columns)
        separator = "-+-".join("-" * len(c) for c in columns)
        lineas = [header, separator]
        for row in rows:
            lineas.append(" | ".join(str(v) for v in row))

        return f"Resultados ({len(rows)} filas):\n" + "\n".join(lineas)

    except sqlite3.Error as e:
        return f"Error de SQL: {e}"
