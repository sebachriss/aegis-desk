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
    r"(salario|salary|sueldo|password|contraseña|token|api[_-]?key|secret|iban|cvv)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

# IBAN español/pan-europeo: dos letras seguidas de 2-34 caracteres alfanumericos
IBAN_PATTERN = re.compile(
    r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[A-Z0-9]{4}){1,7}[ ]?\b",
    re.IGNORECASE,
)

# Tarjetas de credito/débito (Visa, Mastercard, Amex, Discover)
CARD_PATTERN = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b",
)

# Direcciones fisicas simples (calle/av/plaza + numero, CP opcional)
ADDRESS_PATTERN = re.compile(
    r"\b(Calle|Avda?\.?|Avenida|Plaza|Paseo|C/|Ctra\.?|Ronda|Cami)\s+[^,\n]{5,60}\b",
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


def mask_iban(match) -> str:
    """Enmascara un IBAN dejando visibles pais y ultimos 4."""
    iban = match.group().replace(" ", "")
    if len(iban) > 8:
        return f"{iban[:2]} **** **** {iban[-4:]}"
    return "** **** **"


def mask_card(match) -> str:
    """Enmascara un numero de tarjeta: 1234 5678 9012 3456 → **** **** **** 3456."""
    card = match.group().replace(" ", "").replace("-", "")
    if len(card) >= 4:
        return "**** **** **** " + card[-4:]
    return "****"


def mask_address(match) -> str:
    """Enmascara direcciones fisicas."""
    return "[DIRECCION OCULTA]"


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

    # IBANs
    def iban_replacer(match):
        original = match.group()
        masked = mask_iban(match)
        detections.append({"type": "iban", "original": original, "masked": masked})
        return masked

    text = IBAN_PATTERN.sub(iban_replacer, text)

    # Tarjetas de credito/debito
    def card_replacer(match):
        original = match.group()
        masked = mask_card(match)
        detections.append({"type": "card", "original": original, "masked": masked})
        return masked

    text = CARD_PATTERN.sub(card_replacer, text)

    # Direcciones fisicas
    def address_replacer(match):
        original = match.group()
        masked = mask_address(match)
        detections.append({"type": "address", "original": original, "masked": masked})
        return masked

    text = ADDRESS_PATTERN.sub(address_replacer, text)

    return text, detections
