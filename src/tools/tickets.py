"""Herramienta simulada de tickets de soporte.

Las funciones usan el decorador @tool de LangChain para convertirse
en herramientas que el LLM puede invocar via function calling.

Los tickets se guardan en una lista en memoria (simulado, sin DB real).
"""

from langchain_core.tools import tool

# "Base de datos" simulada — lista en memoria
# En produccion seria una DB real (SQLite, PostgreSQL, etc.)
_tickets_db: list[dict] = [
    {"id": 1, "titulo": "VPN no conecta", "descripcion": "Cliente VPN falla al autenticar", "prioridad": "media", "estado": "abierto"},
    {"id": 2, "titulo": "Laptop lenta", "descripcion": "Laptop tarda 5 min en iniciar", "prioridad": "baja", "estado": "abierto"},
    {"id": 3, "titulo": "Email no llega", "descripcion": "No recibo emails de dominios externos", "prioridad": "alta", "estado": "cerrado"},
]
_next_id = 4


@tool
def crear_ticket(titulo: str, descripcion: str, prioridad: str) -> str:
    """Crea un nuevo ticket de soporte en el sistema.

    Args:
        titulo: Resumen corto del problema (max 100 caracteres).
        descripcion: Detalle del problema reportado.
        prioridad: Nivel de urgencia: "baja", "media" o "alta".

    Returns:
        Confirmacion con el ID del ticket creado.
    """
    global _next_id

    if prioridad not in ("baja", "media", "alta"):
        return f"Error: prioridad '{prioridad}' no valida. Usa: baja, media, o alta."

    ticket = {
        "id": _next_id,
        "titulo": titulo,
        "descripcion": descripcion,
        "prioridad": prioridad,
        "estado": "abierto",
    }
    _tickets_db.append(ticket)
    _next_id += 1

    return f"Ticket #{ticket['id']} creado con prioridad '{prioridad}'. Titulo: {titulo}. Estado: abierto."


@tool
def listar_tickets(estado: str = "todos") -> str:
    """Lista los tickets de soporte existentes.

    Args:
        estado: Filtrar por estado: "abierto", "cerrado", o "todos" (default).

    Returns:
        Lista de tickets formateada, o mensaje si no hay resultados.
    """
    if estado == "todos":
        tickets = _tickets_db
    else:
        tickets = [t for t in _tickets_db if t["estado"] == estado]

    if not tickets:
        return f"No hay tickets con estado '{estado}'."

    lineas = []
    for t in tickets:
        lineas.append(f"#{t['id']} [{t['prioridad']}] {t['titulo']} - {t['estado']}")

    return f"Tickets ({len(tickets)}):\n" + "\n".join(lineas)


@tool
def buscar_ticket(ticket_id: int) -> str:
    """Busca un ticket por su ID y muestra todos sus detalles.

    Args:
        ticket_id: ID numerico del ticket a buscar.

    Returns:
        Detalles completos del ticket, o mensaje si no existe.
    """
    for t in _tickets_db:
        if t["id"] == ticket_id:
            return (
                f"Ticket #{t['id']}\n"
                f"  Titulo: {t['titulo']}\n"
                f"  Descripcion: {t['descripcion']}\n"
                f"  Prioridad: {t['prioridad']}\n"
                f"  Estado: {t['estado']}"
            )

    return f"No se encontro el ticket #{ticket_id}."
