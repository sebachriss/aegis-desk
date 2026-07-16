"""Retriever: busca chunks relevantes en la base de datos vectorial.

Por defecto usa Chroma local. Si PINECONE_API_KEY está configurado,
usa Pinecone como backend vectorial.
"""

from langchain_chroma import Chroma

from src.config import get_settings
from src.db.pinecone_store import is_pinecone_configured, search as pinecone_search
from src.rag.embeddings import EMBEDDING_MODEL, LocalEmbeddings
from src.rag.ingest import CHROMA_DIR

# Singleton del vectorstore (se carga una sola vez)
_vectorstore: Chroma | None = None


def _get_chroma_vectorstore() -> Chroma:
    """Carga la base Chroma del disco (persistente)."""
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
    """Busca los k chunks mas relevantes para una pregunta."""
    if is_pinecone_configured():
        return pinecone_search(query, k=k)

    vectorstore = _get_chroma_vectorstore()
    results = vectorstore.similarity_search_with_score(query, k=k)

    chunks = []
    for doc, score in results:
        chunks.append({
            "content": doc.page_content,
            "source": doc.metadata.get("source", "desconocido"),
            "score": round(score, 4),
        })

    return chunks
