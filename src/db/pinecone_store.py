"""Adaptador opcional de Pinecone para el vector store de Aegis Desk."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import get_settings
from src.rag.embeddings import get_embeddings

if TYPE_CHECKING:
    from pinecone import Index


def is_pinecone_configured() -> bool:
    """Devuelve True si hay credenciales de Pinecone configuradas."""
    settings = get_settings()
    return bool(settings.pinecone_api_key and settings.pinecone_index)


def _get_client():
    try:
        from pinecone import Pinecone
    except ImportError as exc:
        raise RuntimeError("Paquete 'pinecone' no instalado. Ejecuta: pip install pinecone") from exc
    settings = get_settings()
    return Pinecone(api_key=settings.pinecone_api_key)


def _get_index() -> "Index":
    settings = get_settings()
    client = _get_client()
    return client.Index(settings.pinecone_index)


def _embed(texts: list[str]) -> list[list[float]]:
    embeddings = get_embeddings()
    return embeddings.embed_documents(texts)


def upsert_documents(documents: list[dict], batch_size: int = 100) -> None:
    settings = get_settings()
    index = _get_index()
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i+batch_size]
        vectors = []
        for doc in batch:
            embedding = _embed([doc["content"]])[0]
            vectors.append({
                "id": doc["id"],
                "values": embedding,
                "metadata": {"source": doc.get("source", ""), "content": doc["content"][:1000]},
            })
        index.upsert(vectors=vectors, namespace=settings.pinecone_namespace)


def search(query: str, k: int = 3) -> list[dict]:
    settings = get_settings()
    index = _get_index()
    embedding = _embed([query])[0]
    result = index.query(vector=embedding, top_k=k, namespace=settings.pinecone_namespace, include_metadata=True)
    chunks = []
    for match in result.matches or []:
        metadata = match.metadata or {}
        chunks.append({
            "content": metadata.get("content", ""),
            "source": metadata.get("source", "desconocido"),
            "score": round(match.score or 0.0, 4),
        })
    return chunks
