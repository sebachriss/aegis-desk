from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración central del proyecto. Lee automáticamente del archivo .env."""

    # API Key de DeepInfra — obligatoria, sin default
    deepinfra_api_key: str = Field(description="API key de DeepInfra")

    # URL base de la API de DeepInfra (formato OpenAI-compatible)
    deepinfra_base_url: str = Field(
        default="https://api.deepinfra.com/v1/openai",
        description="Base URL de la API de DeepInfra",
    )

    # Modelo principal a usar
    deepinfra_model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash",
        description="Nombre del modelo en DeepInfra",
    )

    # Modelo rápido para nodos livianos (supervisor, crítico)
    deepinfra_fast_model: str = Field(
        default="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        description="Modelo rápido para clasificación y evaluación",
    )

    # Groq (free tier) — para nodos livianos: supervisor y crítico
    groq_api_key: str = Field(
        default="",
        description="API key de Groq (free tier, Llama-3.1-8B-Instant)",
    )
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL de la API de Groq",
    )
    groq_model: str = Field(
        default="llama-3.1-8b-instant",
        description="Modelo rápido de Groq para clasificación y evaluación",
    )

    # Parámetros de generación
    temperature: float = Field(
        default=0.7,
        description="Creatividad del LLM (0 = determinista, 1 = muy creativo)",
    )
    max_tokens: int = Field(
        default=1024,
        description="Máximo de tokens a generar por respuesta",
    )

    # JWT secret para auth (opcional, default para demo)
    jwt_secret: str = Field(
        default="aegis-desk-demo-secret-change-in-production",
        description="Secret para firmar JWT tokens",
    )

    # LangSmith (opcional — si no está seteado, tracing local)
    langsmith_api_key: str = Field(
        default="",
        description="API key de LangSmith para tracing visual",
    )
    langsmith_project: str = Field(
        default="aegis-desk",
        description="Nombre del proyecto en LangSmith",
    )
    langsmith_tracing: bool = Field(
        default=False,
        description="Habilitar tracing de LangSmith",
    )

    # Configuración de pydantic-settings
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia única de Settings (singleton cacheado)."""
    return Settings()
