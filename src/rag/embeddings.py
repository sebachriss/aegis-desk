"""Modelos de embeddings para RAG.

Soporta:
  - SentenceTransformer local (offline, sin costo).
  - OpenAI-compatible embeddings API de DeepInfra (multilingüe, remoto).

La elección se hace a través de `get_embeddings()` leyendo `DEEPINFRA_API_KEY`.
"""

from langchain_openai import OpenAIEmbeddings
from sentence_transformers import SentenceTransformer

from src.config import get_settings

DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"
DEFAULT_DEEPINFRA_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
# 1024 es compatible con índices pgvector (límite 2000 dims) y aprovecha
# Matryoshka Representation Learning (MRL) de Qwen3.
DEFAULT_EMBEDDING_DIMENSION = 1024


class LocalEmbeddings:
    """Wrapper para usar sentence-transformers como modelo de embeddings local."""

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para una lista de textos."""
        if not texts:
            return []
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Genera embedding para un texto."""
        embedding = self.model.encode([text], convert_to_numpy=True)
        return embedding[0].tolist()


def get_embeddings() -> OpenAIEmbeddings | LocalEmbeddings:
    """Factory que devuelve el modelo de embeddings configurado.

    - Si `DEEPINFRA_API_KEY` está seteado, usa OpenAIEmbeddings apuntando a
      `https://api.deepinfra.com/v1/openai`.
    - Si no, cae al modelo local `all-MiniLM-L6-v2`.
    """
    settings = get_settings()
    if settings.deepinfra_api_key:
        return OpenAIEmbeddings(
            model=settings.deepinfra_embedding_model or DEFAULT_DEEPINFRA_EMBEDDING_MODEL,
            api_key=settings.deepinfra_api_key,
            base_url=settings.deepinfra_base_url,
            # pgvector soporta hasta 2000 dims con índice hnsw. Qwen3 soporta
            # Matryoshka (MRL), así que pedimos las primeras N dimensiones.
            dimensions=settings.embedding_dimension or DEFAULT_EMBEDDING_DIMENSION,
            # DeepInfra espera cadenas en `input`, no listas de tokens.
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
            max_retries=3,
        )
    return LocalEmbeddings(model_name=DEFAULT_LOCAL_MODEL)


def get_embedding_dimension() -> int:
    """Devuelve la dimensión de los embeddings que se van a generar.

    Debe coincidir con el esquema de la base de datos vectorial.
    """
    settings = get_settings()
    if settings.deepinfra_api_key:
        return settings.embedding_dimension or DEFAULT_EMBEDDING_DIMENSION
    return 384
