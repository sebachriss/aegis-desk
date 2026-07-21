"""Detector de prompt injection.

Busca patrones comunes de intentos de manipular al LLM, incluyendo:
- Instrucciones de override
- Extracción de system prompt
- Jailbreaks clásicos
- RAG poisoning (etiquetas [SYSTEM], <system>, comentarios)
- Unicode confusables / homoglifos
- Payloads codificados en Base64
- Inyección indirecta vía HTML/markdown y espacios extra

No es perfecto (ningún detector lo es), pero bloquea los ataques más obvios.
En producción se combinaría con un modelo de clasificación de LLM.
"""

import base64
import re
import unicodedata

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
    r"pretend\s+(you\s+are|to\s+be)\s+(an?\s+)?(admin|root|developer|system)",
    r"i\s+am\s+(an?\s+)?(admin|root|developer|system)",
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
    r"\[\s*(system|admin|instruction|override|prompt)\s*\]",
    r"</?\s*(system|admin|instruction|override|prompt)\s*>",
    r"#{1,6}\s*(system|admin|instruction|override|prompt).*",
    r"\b(system|admin|instruction|override|prompt)\s*[:=]\s*(ignore|override|new|reveal|show|display|print)",

    # Inyección indirecta vía HTML/markdown o "ignore above"
    r"<\s*!?--.*?--\s*>",
    r"ignore\s+(the\s+)?above.*?(reveal|show|print)",
    r"ignora\s+(lo\s+)?anterior.*?(revela|muestra|imprime)",
    r"<(script|iframe|object|embed|form|input|meta|link|style)\b[^>]*>",

    # SQL injection destructivo
    r"\bDROP\s+(TABLE|DATABASE)\b",
    r"\bDELETE\s+FROM\b",
    r"\bINSERT\s+INTO\b",
    r"\bUPDATE\s+\w+\s+SET\b",
    r"\bALTER\s+TABLE\b.*\bDROP\b",
    r"\bUNION\b.*\bSELECT\b",
    r"\bSELECT\b.*\bpassword\b.*\bFROM\b",

    # Bypass de HITL / replay de acciones
    r"vuelve\s+a\s+ejecutar",
    r"re-?ejecutar.*(acción|HITL|aprobación)",
    r"sin\s+(pedir|necesitar)\s+aprobación",
    r"sin\s+aprobar",
    r"(reenviar|enviar)\s+(el\s+)?(email|correo)\s+(de\s+nuevo|nuevamente|otra\s+vez|sin\s+aprobar)",

    # Exfiltración de datos a dominios externos y tool chaining
    r"\b[A-Za-z0-9._%+-]+@(?!aegiscorp\.com|aegis\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    r"listado\s+de\s+empleados.*(?:email|enviar)",
    r"enviar.*listado.*empleados",
    r"(primero|primera|luego|después|y\s+luego|y\s+después)\s+(crea|crear|envía|enviar).*(crea|crear|envía|enviar)",
]

# Compilar todas las regex case-insensitive
_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

# Frases peligrosas escritas con espacios entre letras (sin espacios para matching)
COMPRESSED_DANGEROUS_PHRASES = [
    "ignoreregla",
    "ignoralasreglas",
    "ignoralosreglamentos",
    "actasadmin",
    "actuacomoadmin",
    "actuacomoadministrador",
    "actuacomosistema",
    "youarenowadmin",
    "youarenowroot",
    "youarenowdeveloper",
    "eresahoraadmin",
    "eresahoraroot",
    "eresahoradesarrollador",
    "pretendtobeadmin",
    "pretendyouareadmin",
    "iamanadmin",
    "iamadmin",
    "developermode",
    "danmode",
    "jailbreak",
    "systemprompt",
    "revealsystemprompt",
    "revealprompt",
    "muestraprompt",
    "muestrainstrucciones",
    "droptable",
    "deletefrom",
    "insertinto",
    "update",
    "altertable",
    "[system]",
    "[admin]",
    "<system>",
    "<instruction>",
    "<admin>",
    "systemoverride",
    "adminoverride",
    # Bypass HITL / replay
    "vuelveaejecutar",
    "reejecutar",
    "sinpediraprobacion",
    "sinaprobar",
    "reenviaremail",
    "enviarnuevamente",
    # Exfiltración
    "externalattackercom",
    "listadodeempleados",
    "enviarlistado",
]

# Caracteres confusables (homoglifos) que se normalizan a ASCII
_CONFUSABLES = {
    # Cirílico
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "і": "i", "ј": "j",
    "у": "y", "к": "k", "м": "m", "н": "n", "в": "b", "т": "t", "г": "r", "ь": "b",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Х": "X", "І": "I", "Ј": "J",
    "У": "Y", "К": "K", "М": "M", "Н": "N", "В": "B", "Т": "T", "Г": "R",
    # Griego
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "σ": "s", "ς": "s", "χ": "x", "ι": "i",
    "Α": "A", "Ε": "E", "Ο": "O", "Ρ": "P", "Σ": "S", "Χ": "X", "Ι": "I",
    # Small caps
    "ʀ": "R", "ᴘ": "P", "ᴄ": "C", "ᴍ": "M", "ᴇ": "E", "ᴛ": "T", "ʏ": "Y",
    "ᴏ": "O", "ᴜ": "U", "ꜱ": "S", "ᴅ": "D", "ɢ": "G", "ʜ": "H", "ʙ": "B", "ꜰ": "F",
}
_CONFUSABLE_MAP = str.maketrans(_CONFUSABLES)

# Categorías Unicode invisibles/formato que se eliminan
_INVISIBLE_CATEGORIES = {"Cf", "Cs"}


def _strip_invisible_and_confusables(text: str) -> str:
    """Expande confusables y elimina caracteres invisibles de formato."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CONFUSABLE_MAP)
    text = "".join(
        ch for ch in text if unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
    )
    return text


def _normalize_for_detection(text: str) -> str:
    """Normaliza texto para detectar inyecciones ofuscadas."""
    text = _strip_invisible_and_confusables(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _try_decode_base64(token: str) -> str | None:
    """Intenta decodificar un token Base64 (estándar o URL-safe)."""
    token = token.rstrip("=")
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    for altchars in (None, b"-_"):
        try:
            data = base64.b64decode(padded, altchars=altchars, validate=True)
        except Exception:
            continue
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if decoded and any(c.isalpha() for c in decoded):
            return decoded
    return None


def _clean_for_base64(text: str) -> str:
    """Elimina caracteres que no forman parte del alfabeto Base64."""
    text = _strip_invisible_and_confusables(text)
    return re.sub(r"[^A-Za-z0-9+/=_-]+", "", text)


def _decode_base64_payload(text: str) -> str | None:
    """Busca payloads Base64 en el texto y los decodifica si son válidos."""
    cleaned = _clean_for_base64(text)
    if len(cleaned) >= 12 and len(cleaned) % 4 == 0:
        decoded = _try_decode_base64(cleaned)
        if decoded:
            return decoded

    for token in re.findall(r"[A-Za-z0-9+/\-_]{6,}(?:={0,2})", text):
        decoded = _try_decode_base64(token)
        if decoded:
            return decoded

    return None


def _matches_injection_patterns(text: str) -> dict | None:
    """Comprueba si el texto coincide con algún patrón de inyección."""
    for i, pattern in enumerate(_compiled_patterns):
        match = pattern.search(text)
        if match:
            return {
                "is_injection": True,
                "matched_pattern": INJECTION_PATTERNS[i],
                "matched_text": match.group()[:200],
                "risk_level": "alto",
            }

    # Última capa: frases peligrosas escritas con espacios entre caracteres
    compressed = re.sub(r"\s+", "", text.lower())
    for phrase in COMPRESSED_DANGEROUS_PHRASES:
        if phrase in compressed:
            return {
                "is_injection": True,
                "matched_pattern": f"[compressed] {phrase}",
                "matched_text": phrase,
                "risk_level": "alto",
            }

    return None


def _has_injection_pattern(text: str) -> bool:
    return _matches_injection_patterns(text) is not None


def _sanitize_base64(text: str) -> str:
    """Reemplaza tokens Base64 que decodifiquen a una inyección."""
    def _repl(match: re.Match) -> str:
        token = match.group(0)
        if len(token) < 8:
            return token
        decoded = _try_decode_base64(token)
        if decoded and _has_injection_pattern(decoded):
            return "[BLOQUEADO]"
        return token

    return re.sub(r"[A-Za-z0-9+/\-_]{6,}(?:={0,2})", _repl, text)


def detect_prompt_injection(text: str) -> dict:
    """Detecta si un texto contiene intentos de prompt injection.

    Maneja Unicode confusables, payloads Base64, HTML/markdown y espacios extra.

    Args:
        text: Texto del usuario o de un documento.

    Returns:
        Diccionario con:
          - is_injection: True si se detectó patrón sospechoso
          - matched_pattern: El patrón que coincidió (o None)
          - matched_text: El texto que coincidió (o None)
          - risk_level: "alto" si hay match, "bajo" si no
    """
    # 1. Texto original
    match = _matches_injection_patterns(text)
    if match:
        return match

    # 2. Payloads codificados en Base64
    decoded = _decode_base64_payload(text)
    if decoded:
        match = _matches_injection_patterns(decoded)
        if match:
            match["matched_text"] = f"[Base64] {match['matched_text'][:120]}"
            return match

    # 3. Unicode confusables / homoglifos y espacios extra
    normalized = _normalize_for_detection(text)
    match = _matches_injection_patterns(normalized)
    if match:
        match["matched_text"] = f"[normalized] {match['matched_text'][:120]}"
        return match

    return {
        "is_injection": False,
        "matched_pattern": None,
        "matched_text": None,
        "risk_level": "bajo",
    }


def sanitize_input(text: str) -> str:
    """Escapa etiquetas y neutraliza ofuscaciones que podrían interpretarse como instrucciones.

    - Normaliza confusables Unicode e invisibles
    - Descodifica y bloquea payloads Base64 maliciosos
    - Colapsa espacios extra
    - Escapa/bloquea etiquetas [SYSTEM], <system>, markdown de override y HTML
    """
    # 1. Expandir confusables y eliminar invisibles
    text = _strip_invisible_and_confusables(text)

    # 2. Detectar y neutralizar payloads Base64 completos
    cleaned = _clean_for_base64(text)
    if len(cleaned) >= 12 and len(cleaned) % 4 == 0:
        decoded = _try_decode_base64(cleaned)
        if decoded and _has_injection_pattern(decoded):
            return "[BLOQUEADO]"

    # 3. Neutralizar tokens Base64 incrustados
    text = _sanitize_base64(text)

    # 4. Colapsar espacios/tab extra (preservar saltos de línea)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 5. Escapar/bloquear etiquetas de sistema/admin con posibles espacios
    text = re.sub(
        r"\[\s*(system|admin|instruction|override|prompt)\s*\]",
        "[BLOQUEADO]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"</?\s*(system|admin|instruction|override|prompt)\s*>",
        r"&lt;\1&gt;",
        text,
        flags=re.IGNORECASE,
    )

    # 6. Eliminar/bloquear cabeceras markdown de override
    text = re.sub(
        r"^#{1,6}\s*(system|admin|instruction|override|prompt).*$",
        "[BLOQUEADO]",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # 7. Eliminar comentarios HTML
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 8. Bloquear etiquetas HTML peligrosas
    text = re.sub(
        r"</?(script|iframe|object|embed|form|input|meta|link|style)\b[^>]*>",
        "[BLOQUEADO]",
        text,
        flags=re.IGNORECASE,
    )

    # 9. Ofuscaciones tipo "system: ignore instructions"
    text = re.sub(
        r"\b(system|admin|instruction|override|prompt)\s*[:=]\s*(ignore|override|reveal|new|show|display|print).*",
        "[BLOQUEADO]",
        text,
        flags=re.IGNORECASE,
    )

    return text
