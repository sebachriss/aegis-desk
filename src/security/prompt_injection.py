"""Detector de prompt injection.

Busca patrones comunes de intentos de manipular al LLM:
- "ignora las instrucciones", "ignore previous instructions"
- "you are now", "act as", "pretend you are"
- "system prompt", "reveal your instructions"
- Intentos de override de rol

No es perfecto (ningún detector lo es), pero bloquea los ataques más obvios.
En producción se combinaría con un modelo de clasificación de LLM.
"""

import re

# Patrones de prompt injection (case-insensitive)
# Cada patrón es una regex que busca frases sospechosas
INJECTION_PATTERNS = [
    # Ignorar instrucciones
    r"ignor[ae]\s+(las?\s+)?(instrucciones|reglas|prompt)",
    r"ignore\s+(previous|all|your)\s+(instructions|rules|prompt)",
    r"disregard\s+(previous|all|your)",

    # Override de rol
    r"you\s+are\s+now\s+(an?\s+)?(admin|root|developer|system)",
    r"act\s+as\s+(if\s+you\s+are\s+)?(admin|root|developer|system)",
    r"pretend\s+(you\s+are|to\s+be)\s+(an?\s+)?(admin|root|developer)",
    r"eres\s+(ahora|un)\s+(admin|root|desarrollador|sistema)",
    r"actua\s+como\s+(un\s+)?(admin|root|desarrollador|sistema)",

    # Revelar system prompt
    r"(reveal|show|print|display)\s+(your\s+)?(system\s+)?prompt",
    r"(muestra|revela|imprime)\s+(tu\s+)?(prompt|instrucciones)",

    # Jailbreak clásico
    r"DAN\s+mode",
    r"developer\s+mode",
    r"jailbreak",

    # Inyección desde documentos (RAG poisoning)
    r"\[SYSTEM\]",
    r"\[ADMIN\]",
    r"<\s*system\s*>",
    r"<\s*instruction\s*>",

    # SQL injection destructivo
    r"\bDROP\s+(TABLE|DATABASE)\b",
    r"\bDELETE\s+FROM\b",
    r"\bINSERT\s+INTO\b",
    r"\bUPDATE\s+\w+\s+SET\b",
    r"\bALTER\s+TABLE\b.*\bDROP\b",
]

# Compilar todas las regex case-insensitive
_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def detect_prompt_injection(text: str) -> dict:
    """Detecta si un texto contiene intentos de prompt injection.

    Args:
        text: Texto del usuario o de un documento.

    Returns:
        Diccionario con:
          - is_injection: True si se detectó patrón sospechoso
          - matched_pattern: El patrón que coincidió (o None)
          - risk_level: "alto" si hay match, "bajo" si no
    """
    for i, pattern in enumerate(_compiled_patterns):
        match = pattern.search(text)
        if match:
            return {
                "is_injection": True,
                "matched_pattern": INJECTION_PATTERNS[i],
                "matched_text": match.group(),
                "risk_level": "alto",
            }

    return {
        "is_injection": False,
        "matched_pattern": None,
        "matched_text": None,
        "risk_level": "bajo",
    }


def sanitize_input(text: str) -> str:
    """Escapa etiquetas que podrían interpretarse como instrucciones de sistema.

    Reemplaza [SYSTEM], <system>, etc. con texto plano inofensivo.
    """
    sanitized = text
    sanitized = re.sub(r"\[SYSTEM\]", "[BLOQUEADO]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\[ADMIN\]", "[BLOQUEADO]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<\s*system\s*>", "&lt;system&gt;", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<\s*instruction\s*>", "&lt;instruction&gt;", sanitized, flags=re.IGNORECASE)
    return sanitized
