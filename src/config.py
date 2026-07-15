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

    # Parámetros de generación
    temperature: float = Field(
        default=0.7,
        description="Creatividad del LLM (0 = determinista, 1 = muy creativo)",
    )
    max_tokens: int = Field(
        default=1024,
        description="Máximo de tokens a generar por respuesta",
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
