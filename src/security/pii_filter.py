"""Filtro de PII (Personally Identifiable Information).

Detecta y enmascara información sensible en las respuestas del LLM:
- Emails corporativos
- Números de teléfono
- DNIs / IDs numéricos largos

Esto previene que el LLM exponga datos sensibles en sus respuestas.
"""

import re

# Patrones de PII
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

PHONE_PATTERN = re.compile(
    r"\b(?:\+?34\s?)?(?:6\d{2}|7\d{2}|9\d{2})\s?\d{3}\s?\d{3}\b"
)

DNI_PATTERN = re.compile(
    r"\b\d{8}[A-Za-z]\b"
)

# Campos sensibles en texto (ej: "salario: 75000")
SENSITIVE_DATA_PATTERN = re.compile(
    r"(salario|salary|sueldo|password|contraseña|token|api[_-]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def mask_email(match) -> str:
    """Enmascara un email: ana@aegiscorp.com → a***@aegiscorp.com"""
    email = match.group()
    parts = email.split("@")
    if len(parts) == 2:
        return f"{parts[0][0]}***@{parts[1]}"
    return "***@***.***"


def mask_phone(match) -> str:
    """Enmascara un teléfono: +34 666 123 456 → +34 *** *** ***"""
    return re.sub(r"\d", "*", match.group())


def mask_dni(match) -> str:
    """Enmascara un DNI: 12345678A → ********A"""
    dni = match.group()
    return "*" * 8 + dni[-1]


def mask_sensitive_data(match) -> str:
    """Enmascara datos sensibles: salario: 75000 → salario: ***"""
    full = match.group()
    # Preservar la clave, enmascarar el valor
    parts = re.split(r"[:=]", full, maxsplit=1)
    if len(parts) == 2:
        return f"{parts[0]}: ***"
    return "***"


def filter_pii(text: str) -> tuple[str, list[dict]]:
    """Detecta y enmascara PII en un texto.

    Args:
        text: Texto a filtrar (típicamente la respuesta del LLM).

    Returns:
        Tupla de:
          - Texto filtrado con PII enmascarada
          - Lista de detecciones: [{"type": "email", "original": "...", "masked": "..."}]
    """
    detections = []

    # Emails
    def email_replacer(match):
        original = match.group()
        masked = mask_email(match)
        detections.append({"type": "email", "original": original, "masked": masked})
        return masked

    text = EMAIL_PATTERN.sub(email_replacer, text)

    # Teléfonos
    def phone_replacer(match):
        original = match.group()
        masked = mask_phone(match)
        detections.append({"type": "phone", "original": original, "masked": masked})
        return masked

    text = PHONE_PATTERN.sub(phone_replacer, text)

    # DNIs
    def dni_replacer(match):
        original = match.group()
        masked = mask_dni(match)
        detections.append({"type": "dni", "original": original, "masked": masked})
        return masked

    text = DNI_PATTERN.sub(dni_replacer, text)

    # Datos sensibles (salario, password, etc.)
    def sensitive_replacer(match):
        original = match.group()
        masked = mask_sensitive_data(match)
        detections.append({"type": "sensitive", "original": original, "masked": masked})
        return masked

    text = SENSITIVE_DATA_PATTERN.sub(sensitive_replacer, text)

    return text, detections
