"""Herramienta simulada de envio de email.

Simula enviar emails internos. No envia nada real,
solo registra el envio y devuelve confirmacion.
"""

from langchain_core.tools import tool

# Log de emails enviados (simulado)
_emails_enviados: list[dict] = []


@tool
def enviar_email(para: str, asunto: str, cuerpo: str) -> str:
    """Envia un email interno a un empleado o departamento.

    Args:
        para: Direccion de email del destinatario (ej: "rrhh@aegiscorp.com").
        asunto: Asunto del email (max 200 caracteres).
        cuerpo: Contenido del mensaje.

    Returns:
        Confirmacion del envio.
    """
    email = {
        "para": para,
        "asunto": asunto,
        "cuerpo": cuerpo,
        "estado": "enviado",
    }
    _emails_enviados.append(email)

    return f"Email enviado a {para}. Asunto: {asunto}."
