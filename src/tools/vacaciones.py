"""Herramientas de gestión de vacaciones.

Implementación triple-backend (Postgres -> Supabase REST -> SQLite),
mismo patrón que `src/tools/tickets.py`.

Seguridad:
- `created_by` y `role` se inyectan en `action_executor_node`; la tool no confía
  en los argumentos del LLM.
- Validaciones deterministas fail-closed antes de tocar la base de datos.
- El descuento de saldo y la inserción de la solicitud ocurren en la misma
  transacción.
- `idempotency_key` evita doble descuento si se re-ejecuta el mismo action_plan.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool

from src.config import get_settings
from src.db.postgres_utils import get_postgres_connection
from src.db.supabase_client import get_supabase_service_client, is_supabase_configured
from src.security.prompt_injection import sanitize_input
from src.tools.sql import _init_db

DB_PATH = Path(__file__).parent.parent.parent / "data" / "aegis.db"


def _use_postgres() -> bool:
    """Devuelve True si hay una DATABASE_URL configurada."""
    settings = get_settings()
    return bool(settings.database_url)


def _init_sqlite():
    """Crea la base de datos simulada con datos de ejemplo si no existe."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _init_db()


def _get_sqlite_connection():
    """Abre una conexion SQLite local (legacy)."""
    _init_sqlite()
    import sqlite3

    return sqlite3.connect(str(DB_PATH))


def _dias_habiles(fecha_inicio: date, fecha_fin: date) -> int:
    """Cuenta días hábiles (lun-vie) entre dos fechas inclusive de forma eficiente."""
    total_dias = (fecha_fin - fecha_inicio).days + 1
    if total_dias <= 0:
        return 0
    semanas_completas = total_dias // 7
    extra = total_dias % 7
    habiles = semanas_completas * 5
    inicio = fecha_inicio.weekday()
    for i in range(extra):
        if (inicio + i) % 7 < 5:
            habiles += 1
    return habiles


def _validar_solicitud_vacaciones(arguments: dict) -> str | None:
    """Validación determinista de una solicitud de vacaciones.

    Devuelve un mensaje de error si no pasa las validaciones, None si es válida.
    """
    fecha_inicio = arguments.get("fecha_inicio", "")
    fecha_fin = arguments.get("fecha_fin", "")

    if not fecha_inicio or not fecha_fin:
        return "Error: debes proporcionar fecha_inicio y fecha_fin."

    try:
        fi = date.fromisoformat(fecha_inicio)
        ff = date.fromisoformat(fecha_fin)
    except (ValueError, TypeError):
        return "Error: formato de fecha inválido. Usa YYYY-MM-DD."

    hoy = date.today()
    if fi < hoy:
        return "Error: la fecha de inicio no puede ser anterior a hoy."
    if ff < fi:
        return "Error: la fecha de fin no puede ser anterior a la de inicio."

    dias_solicitados = _dias_habiles(fi, ff)
    if dias_solicitados <= 0:
        return "Error: el rango no incluye días hábiles."
    if dias_solicitados > 20:
        return "Error: no se pueden solicitar más de 20 días hábiles por solicitud."

    return None


def _resolve_empleado_email(conn, identifier: str, is_postgres: bool = False) -> str:
    """Resuelve un identificador (email o username) al email almacenado en vacaciones_saldo.

    Si `identifier` ya existe en `vacaciones_saldo` se devuelve tal cual.
    Si no y no contiene '@', intenta mapear username -> email usando `empleados`.
    """
    if not identifier:
        return identifier

    # Caso feliz: identifier ya está registrado
    if is_postgres:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM vacaciones_saldo WHERE empleado_email = %s", (identifier,))
            if cur.fetchone():
                return identifier
    else:
        row = conn.execute(
            "SELECT 1 FROM vacaciones_saldo WHERE empleado_email = ?", (identifier,)
        ).fetchone()
        if row:
            return identifier

    # Intentar mapear username (ana.garcia) al email de empleados (ana@aegiscorp.com)
    if "@" not in identifier:
        parts = identifier.lower().replace("_", ".").split(".")
        first = parts[0]
        last = parts[-1]
        if is_postgres:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT email FROM empleados WHERE LOWER(nombre) LIKE %s AND LOWER(nombre) LIKE %s",
                    (f"%{first}%", f"%{last}%"),
                )
                row = cur.fetchone()
                if row:
                    return row[0]
        else:
            row = conn.execute(
                "SELECT email FROM empleados WHERE LOWER(nombre) LIKE ? AND LOWER(nombre) LIKE ?",
                (f"%{first}%", f"%{last}%"),
            ).fetchone()
            if row:
                return row[0]

    return identifier


@tool
def consultar_saldo_vacaciones(
    created_by: str = "",
    role: str = "empleado",
    empleado_email: str | None = None,
) -> str:
    """Consulta el saldo de vacaciones de un empleado.

    Args:
        created_by: Usuario autenticado (inyectado por el executor).
        role: Rol del usuario (empleado/admin).
        empleado_email: Solo para admin: email/username del empleado a consultar.

    Returns:
        Saldo con días totales, usados y disponibles.
    """
    if not created_by:
        return "Error: identificador de empleado requerido."

    is_admin = role == "admin"
    target = empleado_email if is_admin and empleado_email else created_by

    if not is_admin and empleado_email and empleado_email != created_by:
        return "Error: no puedes consultar el saldo de otro empleado."

    if _use_postgres():
        with get_postgres_connection() as conn:
            target = _resolve_empleado_email(conn, target, is_postgres=True)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT dias_totales, dias_usados, anio FROM vacaciones_saldo WHERE empleado_email = %s",
                    (target,),
                )
                row = cur.fetchone()
        if not row:
            return f"Error: no se encontró saldo de vacaciones para {target}."
        totales, usados, anio = row
        disponibles = totales - usados
        return f"Saldo de vacaciones de {target} (año {anio}): totales {totales}, usados {usados}, disponibles {disponibles}."

    if is_supabase_configured():
        client = get_supabase_service_client()
        response = client.table("vacaciones_saldo").select("*").eq("empleado_email", target).execute()
        rows = response.data
        if not rows:
            return f"Error: no se encontró saldo de vacaciones para {target}."
        row = rows[0]
        disponibles = row["dias_totales"] - row["dias_usados"]
        return (
            f"Saldo de vacaciones de {target} (año {row['anio']}): "
            f"totales {row['dias_totales']}, usados {row['dias_usados']}, disponibles {disponibles}."
        )

    conn = _get_sqlite_connection()
    try:
        target = _resolve_empleado_email(conn, target, is_postgres=False)
        row = conn.execute(
            "SELECT dias_totales, dias_usados, anio FROM vacaciones_saldo WHERE empleado_email = ?",
            (target,),
        ).fetchone()
        if not row:
            return f"Error: no se encontró saldo de vacaciones para {target}."
        totales, usados, anio = row
        disponibles = totales - usados
        return f"Saldo de vacaciones de {target} (año {anio}): totales {totales}, usados {usados}, disponibles {disponibles}."
    finally:
        conn.close()


@tool
def solicitar_vacaciones(
    fecha_inicio: str,
    fecha_fin: str,
    motivo: str = "",
    created_by: str = "",
    role: str = "empleado",
    idempotency_key: str = "",
    aprobado_por: str = "",
) -> str:
    """Solicita días de vacaciones y descuenta el saldo tras aprobación HITL.

    Args:
        fecha_inicio: Inicio en formato YYYY-MM-DD.
        fecha_fin: Fin en formato YYYY-MM-DD.
        motivo: Motivo de la solicitud (texto libre, sanitizado).
        created_by: Usuario solicitante (inyectado por el executor).
        role: Rol del usuario.
        idempotency_key: Clave para prevenir doble descuento.
        aprobado_por: Usuario admin que aprobó la solicitud (inyectado por HITL).

    Returns:
        Confirmación con el ID de la solicitud y saldo restante.

    Raises:
        ValueError: Si falla alguna validación o el saldo es insuficiente.
    """
    if not created_by:
        raise ValueError("Error: identificador de empleado requerido.")
    if role not in ("empleado", "admin"):
        raise ValueError("Error: rol inválido.")

    error = _validar_solicitud_vacaciones(
        {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin, "motivo": motivo}
    )
    if error:
        raise ValueError(error)

    fi = date.fromisoformat(fecha_inicio)
    ff = date.fromisoformat(fecha_fin)
    dias_solicitados = _dias_habiles(fi, ff)

    # Sanitizar motivo para no persistir inyecciones
    motivo_limpio = sanitize_input(motivo) if motivo else ""

    now = datetime.now().isoformat()

    if _use_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                target = _resolve_empleado_email(conn, created_by, is_postgres=True)
                cur.execute(
                    "SELECT dias_totales, dias_usados FROM vacaciones_saldo WHERE empleado_email = %s FOR UPDATE",
                    (target,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Error: no se encontró saldo de vacaciones para {target}.")
                totales, usados = row
                disponibles = totales - usados
                if dias_solicitados > disponibles:
                    raise ValueError(
                        f"Error: saldo insuficiente. Disponibles: {disponibles} días, solicitados: {dias_solicitados} días."
                    )

                if idempotency_key:
                    cur.execute(
                        "SELECT id FROM vacaciones_solicitudes WHERE idempotency_key = %s AND solicitante = %s",
                        (idempotency_key, target),
                    )
                    if cur.fetchone():
                        raise ValueError("Error: solicitud ya registrada.")

                nuevo_usados = usados + dias_solicitados
                cur.execute(
                    "UPDATE vacaciones_saldo SET dias_usados = %s WHERE empleado_email = %s",
                    (nuevo_usados, target),
                )
                cur.execute(
                    """
                    INSERT INTO vacaciones_solicitudes
                    (solicitante, fecha_inicio, fecha_fin, dias, estado, aprobado_por, created_at, motivo, idempotency_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        target,
                        fecha_inicio,
                        fecha_fin,
                        dias_solicitados,
                        "aprobada",
                        aprobado_por or None,
                        now,
                        motivo_limpio,
                        idempotency_key or None,
                    ),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        return (
            f"Solicitud #{new_id} aprobada. Días hábiles: {dias_solicitados}. "
            f"Saldo disponible restante: {totales - nuevo_usados} días."
        )

    if is_supabase_configured():
        client = get_supabase_service_client()
        response = client.table("vacaciones_saldo").select("*").eq("empleado_email", created_by).execute()
        if not response.data:
            raise ValueError(f"Error: no se encontró saldo de vacaciones para {created_by}.")
        row = response.data[0]
        totales, usados = row["dias_totales"], row["dias_usados"]
        disponibles = totales - usados
        if dias_solicitados > disponibles:
            raise ValueError(f"Error: saldo insuficiente. Disponibles: {disponibles} días.")

        if idempotency_key:
            existing = (
                client.table("vacaciones_solicitudes")
                .select("id")
                .eq("idempotency_key", idempotency_key)
                .eq("solicitante", created_by)
                .execute()
            )
            if existing.data:
                raise ValueError("Error: solicitud ya registrada.")

        nuevo_usados = usados + dias_solicitados
        client.table("vacaciones_saldo").update({"dias_usados": nuevo_usados}).eq(
            "empleado_email", created_by
        ).execute()
        ins = client.table("vacaciones_solicitudes").insert(
            {
                "solicitante": created_by,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "dias": dias_solicitados,
                "estado": "aprobada",
                "aprobado_por": aprobado_por or None,
                "created_at": now,
                "motivo": motivo_limpio,
                "idempotency_key": idempotency_key or None,
            }
        ).execute()
        new_id = ins.data[0]["id"]
        return (
            f"Solicitud #{new_id} aprobada. Días hábiles: {dias_solicitados}. "
            f"Saldo disponible restante: {totales - nuevo_usados} días."
        )

    conn = _get_sqlite_connection()
    try:
        target = _resolve_empleado_email(conn, created_by, is_postgres=False)
        row = conn.execute(
            "SELECT dias_totales, dias_usados FROM vacaciones_saldo WHERE empleado_email = ?",
            (target,),
        ).fetchone()
        if not row:
            raise ValueError(f"Error: no se encontró saldo de vacaciones para {target}.")
        totales, usados = row
        disponibles = totales - usados
        if dias_solicitados > disponibles:
            raise ValueError(
                f"Error: saldo insuficiente. Disponibles: {disponibles} días, solicitados: {dias_solicitados} días."
            )

        if idempotency_key:
            existing = conn.execute(
                "SELECT id FROM vacaciones_solicitudes WHERE idempotency_key = ? AND solicitante = ?",
                (idempotency_key, target),
            ).fetchone()
            if existing:
                raise ValueError("Error: solicitud ya registrada.")

        nuevo_usados = usados + dias_solicitados
        conn.execute(
            "UPDATE vacaciones_saldo SET dias_usados = ? WHERE empleado_email = ?",
            (nuevo_usados, target),
        )
        cursor = conn.execute(
            """
            INSERT INTO vacaciones_solicitudes
            (solicitante, fecha_inicio, fecha_fin, dias, estado, aprobado_por, created_at, motivo, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target,
                fecha_inicio,
                fecha_fin,
                dias_solicitados,
                "aprobada",
                aprobado_por or None,
                now,
                motivo_limpio,
                idempotency_key or None,
            ),
        )
        new_id = cursor.lastrowid
        conn.commit()
        return (
            f"Solicitud #{new_id} aprobada. Días hábiles: {dias_solicitados}. "
            f"Saldo disponible restante: {totales - nuevo_usados} días."
        )
    finally:
        conn.close()


@tool
def listar_solicitudes_vacaciones(
    created_by: str = "",
    role: str = "empleado",
    estado: str = "todos",
) -> str:
    """Lista las solicitudes de vacaciones.

    Args:
        created_by: Usuario autenticado (inyectado por el executor).
        role: Rol del usuario; admin ve todas, empleado solo las propias.
        estado: Filtro por estado: todos, pendiente, aprobada, rechazada, cancelada.

    Returns:
        Lista formateada de solicitudes.
    """
    is_admin = role == "admin"
    if not is_admin and not created_by:
        return "Error: un empleado debe especificar su usuario para listar solicitudes."

    estados_validos = {"todos", "pendiente", "aprobada", "rechazada", "cancelada"}
    if estado not in estados_validos:
        return f"Error: estado '{estado}' no válido. Usa: {', '.join(sorted(estados_validos))}."

    def _format_rows(rows):
        if not rows:
            return f"No hay solicitudes con estado '{estado}'."
        lineas = [
            f"#{r[0]} [{r[5]}] {r[1]}: {r[2]} a {r[3]} ({r[4]} días) - {r[6]}" for r in rows
        ]
        return f"Solicitudes de vacaciones ({len(rows)}):\n" + "\n".join(lineas)

    select_sql = "SELECT id, solicitante, fecha_inicio, fecha_fin, dias, estado, motivo FROM vacaciones_solicitudes"

    if _use_postgres():
        with get_postgres_connection() as conn:
            target = _resolve_empleado_email(conn, created_by, is_postgres=True) if not is_admin else None
            with conn.cursor() as cur:
                if is_admin:
                    if estado == "todos":
                        cur.execute(f"{select_sql} ORDER BY id DESC")
                    else:
                        cur.execute(f"{select_sql} WHERE estado = %s ORDER BY id DESC", (estado,))
                else:
                    if estado == "todos":
                        cur.execute(
                            f"{select_sql} WHERE solicitante = %s ORDER BY id DESC", (target,)
                        )
                    else:
                        cur.execute(
                            f"{select_sql} WHERE solicitante = %s AND estado = %s ORDER BY id DESC",
                            (target, estado),
                        )
                rows = cur.fetchall()
        return _format_rows(rows)

    if is_supabase_configured():
        client = get_supabase_service_client()
        query = client.table("vacaciones_solicitudes").select(
            "id, solicitante, fecha_inicio, fecha_fin, dias, estado, motivo"
        )
        if not is_admin:
            query = query.eq("solicitante", created_by)
        if estado != "todos":
            query = query.eq("estado", estado)
        query = query.order("id", desc=True)
        rows = query.execute().data
        return _format_rows([(r["id"], r["solicitante"], r["fecha_inicio"], r["fecha_fin"], r["dias"], r["estado"], r["motivo"]) for r in rows])

    # Fallback SQLite

    conn = _get_sqlite_connection()
    try:
        target = _resolve_empleado_email(conn, created_by, is_postgres=False) if not is_admin else None
        if is_admin:
            if estado == "todos":
                rows = conn.execute(f"{select_sql} ORDER BY id DESC").fetchall()
            else:
                rows = conn.execute(f"{select_sql} WHERE estado = ? ORDER BY id DESC", (estado,)).fetchall()
        else:
            if estado == "todos":
                rows = conn.execute(
                    f"{select_sql} WHERE solicitante = ? ORDER BY id DESC", (target,)
                ).fetchall()
            else:
                rows = conn.execute(
                    f"{select_sql} WHERE solicitante = ? AND estado = ? ORDER BY id DESC",
                    (target, estado),
                ).fetchall()
        return _format_rows(rows)
    finally:
        conn.close()
