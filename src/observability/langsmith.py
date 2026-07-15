"""Setup de LangSmith tracing para Aegis Desk.

Si LANGSMITH_API_KEY está configurado en .env, habilita tracing automático
de LangChain/LangGraph en LangSmith. Si no, no hace nada (graceful degradation).

Uso:
    from src.observability.langsmith import setup_langsmith_tracing
    setup_langsmith_tracing()  # llamar antes de build_graph()

Para ver los traces:
    1. Crear cuenta en https://smith.langchain.com
    2. Obtener API key
    3. Añadir a .env:
       LANGSMITH_API_KEY=lsv2_pt_...
       LANGSMITH_TRACING=true
       LANGSMITH_PROJECT=aegis-desk
    4. Reiniciar la API
"""

import os

from src.config import get_settings


def setup_langsmith_tracing() -> bool:
    """Configura LangSmith tracing si hay API key disponible.

    Debe llamarse ANTES de crear el grafo o cualquier componente de LangChain,
    porque LangChain lee las variables de entorno al importar.

    Returns:
        True si LangSmith está habilitado, False si no.
    """
    settings = get_settings()

    if not settings.langsmith_api_key:
        return False

    # Setear variables de entorno que LangChain/LangGraph leen automáticamente
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    # LangChain usa LANGCHAIN_TRACING_V2 como flag principal
    if settings.langsmith_tracing:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

    return settings.langsmith_tracing


def is_langsmith_enabled() -> bool:
    """Devuelve True si LangSmith tracing está activo."""
    settings = get_settings()
    return bool(settings.langsmith_api_key) and settings.langsmith_tracing
