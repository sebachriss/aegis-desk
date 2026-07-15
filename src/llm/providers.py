# Abstraccion multi-proveedor con interfaz comun y fallback automatico

from langchain_openai import ChatOpenAI

from src.config import get_settings

settings = get_settings()

# Configuracion de cada proveedor (datos, no instancias)
PROVIDERS = {
    "deepinfra": {
        "base_url": settings.deepinfra_base_url,
        "model": settings.deepinfra_model,
        "api_key": settings.deepinfra_api_key,
    },
    "groq": {
        "base_url": settings.groq_base_url,
        "model": settings.groq_model,
        "api_key": settings.groq_api_key,
    },
}


def get_llm(
    provider: str = "deepinfra",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    streaming: bool = False,
) -> ChatOpenAI:
    """Crea y devuelve un ChatOpenAI configurado para el proveedor indicado.

    Args:
        provider: Nombre del proveedor ("deepinfra"). Debe existir en PROVIDERS.
        model: Modelo a usar. Si es None, usa el default del proveedor.
        temperature: Creatividad. Si es None, usa el default de config.
        max_tokens: Maximo de tokens a generar. Si es None, usa el default de config.
        streaming: Si True, la respuesta se devuelve token por token (async generator).

    Returns:
        ChatOpenAI configurado y listo para usar con .invoke() o .stream().

    Raises:
        ValueError: Si el provider no existe en PROVIDERS.
    """
    # 1. Validar que el proveedor exista
    if provider not in PROVIDERS:
        disponibles = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Proveedor '{provider}' no disponible. Opciones: {disponibles}")

    # 2. Obtener la config del diccionario
    config = PROVIDERS[provider]

    # 3. Usar parametros pasados o defaults
    modelo_final = model or config["model"]
    temp_final = temperature if temperature is not None else settings.temperature
    tokens_final = max_tokens if max_tokens is not None else settings.max_tokens

    # 4. Crear y devolver el ChatOpenAI
    return ChatOpenAI(
        model=modelo_final,
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=temp_final,
        max_tokens=tokens_final,
        streaming=streaming,
    )


def get_fast_llm(
    provider: str = "groq",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 256,
) -> ChatOpenAI:
    """Crea un ChatOpenAI con el modelo rápido de Groq (Llama-3.1-8B-Instant).

    Usado por nodos livianos: supervisor (clasificación) y crítico (evaluación).
    Groq usa chips LPU — ~10x más rápido que GPU. Free tier: 30 req/min.

    Args:
        provider: Nombre del proveedor. Default "groq".
        model: Modelo específico. Si es None, usa el default de Groq.
        temperature: Creatividad. Default 0 para respuestas deterministas.
        max_tokens: Máximo de tokens. Default 256 (suficiente para JSON pequeño).
    """
    return get_llm(
        provider=provider,
        model=model or settings.groq_model,
        temperature=temperature if temperature is not None else 0,
        max_tokens=max_tokens,
    )