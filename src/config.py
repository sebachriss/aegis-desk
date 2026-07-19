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

    # Modelo de embeddings en DeepInfra (OpenAI-compatible)
    deepinfra_embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-8B",
        description="Modelo de embeddings multilingüe en DeepInfra",
    )

    # Dimensión de los embeddings (debe coincidir con el modelo y con pgvector)
    # 1024 funciona con índices hnsw de pgvector (límite 2000) y aprovecha MRL.
    embedding_dimension: int = Field(
        default=1024,
        description="Dimensión de los vectores de embedding",
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

    # Entorno de ejecucion
    environment: str = Field(
        default="development",
        description="Entorno: development, staging, production",
    )

    # JWT secret para auth
    jwt_secret: str = Field(
        default="aegis-desk-demo-secret-change-in-production",
        description="Secret para firmar JWT tokens",
    )
    jwt_issuer: str = Field(
        default="aegis-desk",
        description="Issuer claim del JWT",
    )
    jwt_audience: str = Field(
        default="aegis-desk-api",
        description="Audience claim del JWT",
    )

    # CORS: origenes permitidos (lista separada por comas)
    cors_origins: str = Field(
        default="*",
        description="Origenes CORS permitidos, separados por comas",
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

    # Supabase (opcional — para persistencia en Postgres en producción)
    supabase_url: str = Field(
        default="",
        description="URL del proyecto Supabase (https://<ref>.supabase.co)",
    )
    supabase_key: str = Field(
        default="",
        description="API key anónima de Supabase (role anon)",
    )
    supabase_service_key: str = Field(
        default="",
        description="Service Role Key de Supabase (para operaciones admin/migraciones)",
    )

    # Pinecone (opcional — para vector store en producción)
    pinecone_api_key: str = Field(
        default="",
        description="API key de Pinecone",
    )
    pinecone_index: str = Field(
        default="aegis-desk",
        description="Nombre del índice de Pinecone",
    )
    pinecone_namespace: str = Field(
        default="aegis-docs",
        description="Namespace dentro del índice de Pinecone",
    )

    # Postgres / Supabase (opcional — backend SQL remoto en producción)
    database_url: str = Field(
        default="",
        description="URL de conexión Postgres (ej. Supabase direct connection)",
    )

    hitl_expiration_seconds: int = Field(
        default=600,
        description="Tiempo de expiración de aprobaciones HITL en segundos",
    )

    api_chat_timeout_seconds: float = Field(
        default=30.0,
        description="Timeout máximo para una invocación de /chat",
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
