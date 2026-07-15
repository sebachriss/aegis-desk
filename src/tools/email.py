"""Herramienta simulada de envio de email.

Simula enviar emails internos. No envia nada real,
solo registra el envio y devuelve confirmacion.
Solo permite envíos a dominios internos de Aegis Corp.
"""

from langchain_core.tools import tool

# Log de emails enviados (simulado)
_emails_enviados: list[dict] = []

# Dominios permitidos (internos)
DOMINIOS_PERMITIDOS = {"aegiscorp.com", "aegis.com"}


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
    # Validar dominio del destinatario
    dominio = para.split("@")[-1].lower().strip(">") if "@" in para else ""
    if dominio not in DOMINIOS_PERMITIDOS:
        return (f"No se puede enviar email a {para}. "
                f"Solo se permiten dominios internos ({', '.join(DOMINIOS_PERMITIDOS)}). "
                f"Por seguridad, los envíos a dominios externos están bloqueados.")

    email = {
        "para": para,
        "asunto": asunto,
        "cuerpo": cuerpo,
        "estado": "enviado",
    }
    _emails_enviados.append(email)

    return f"Email enviado a {para}. Asunto: {asunto}."
