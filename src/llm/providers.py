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