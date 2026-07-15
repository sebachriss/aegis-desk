"""Retriever: busca chunks relevantes en la base de datos Chroma.

Carga la base persistente del disco y permite hacer busquedas
por similitud semantica (no por palabras exactas).
"""

from pathlib import Path

from langchain_chroma import Chroma

from src.rag.ingest import CHROMA_DIR, EMBEDDING_MODEL, LocalEmbeddings

# Singleton del vectorstore (se carga una sola vez)
_vectorstore: Chroma | None = None


def get_vectorstore() -> Chroma:
    """Carga la base Chroma del disco (persistente).

    Si ya se cargo antes, devuelve la misma instancia (singleton).
    Si no existe la base, lanza error indicando que hay que correr ingest primero.
    """
    global _vectorstore

    if _vectorstore is not None:
        return _vectorstore

    if not CHROMA_DIR.exists():
        raise RuntimeError(
            f"La base de datos no existe en {CHROMA_DIR}. "
            "Ejecuta 'python -m src.rag.ingest' primero."
        )

    embeddings = LocalEmbeddings(EMBEDDING_MODEL)

    _vectorstore = Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        collection_name="aegis_docs",
    )

    return _vectorstore


def search(query: str, k: int = 3) -> list[dict]:
    """Busca los k chunks mas relevantes para una pregunta.

    Args:
        query: La pregunta del usuario.
        k: Cuantos chunks devolver (default 3).

    Returns:
        Lista de diccionarios con: content (texto), source (archivo), score (similitud).
    """
    vectorstore = get_vectorstore()

    # similarity_search_with_score devuelve tuplas (Document, score)
    # score es distancia (menor = mas similar en Chroma)
    results = vectorstore.similarity_search_with_score(query, k=k)

    chunks = []
    for doc, score in results:
        chunks.append({
            "content": doc.page_content,
            "source": doc.metadata.get("source", "desconocido"),
            "score": round(score, 4),
        })

    return chunks
