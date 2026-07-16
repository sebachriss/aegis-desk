"""Modelo de embeddings local (sentence-transformers) para RAG.

Separa la definición del modelo de ingest/retriever para evitar
imports circulares con adaptadores cloud (Pinecone).
"""

from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class LocalEmbeddings:
    """Wrapper para usar sentence-transformers como modelo de embeddings de LangChain."""

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para una lista de textos."""
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Genera embedding para un texto."""
        embedding = self.model.encode([text], convert_to_numpy=True)
        return embedding[0].tolist()
