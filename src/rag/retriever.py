"""Retriever: busca chunks relevantes en la base de datos vectorial.

Soporta Chroma local, Pinecone y Supabase pgvector. El modelo de embeddings
se obtiene de `get_embeddings()` (DeepInfra o local según `DEEPINFRA_API_KEY`).
"""

from langchain_chroma import Chroma

from src.config import get_settings
from src.db.pinecone_store import is_pinecone_configured, search as pinecone_search
from src.db.supabase_vector import is_supabase_vector_configured, search as supabase_search
from src.rag.embeddings import get_embeddings
from src.rag.ingest import CHROMA_DIR

# Singleton del vectorstore (se carga una sola vez)
_vectorstore: Chroma | None = None

# Umbral de relevancia: chunks con score/similaridad menor son descartados
RELEVANCE_THRESHOLD = 0.3


class _SearchResult(list):
    """Lista de chunks aceptados con metadatos del retrieval.

    Extiende ``list`` para mantener compatibilidad con llamadas que iteran
    chunks, pero añade ``retrieval_scores`` y ``discarded`` para trazabilidad.
    """

    def __init__(self, chunks: list[dict], retrieval_scores: list[float], discarded: int):
        super().__init__(chunks)
        self.retrieval_scores = retrieval_scores
        self.discarded = discarded


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

    embeddings = get_embeddings()

    _vectorstore = Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        collection_name="aegis_docs",
    )

    return _vectorstore


def search(query: str, k: int = 3) -> list[dict]:
    """Busca los k chunks mas relevantes para una pregunta.

    Aplica un umbral de relevancia: los chunks con score menor a
    ``RELEVANCE_THRESHOLD`` se descartan. El resultado conserva los
    scores originales y el número de descartes para trazabilidad.
    """
    if is_pinecone_configured():
        raw_chunks = pinecone_search(query, k=k)

    elif is_supabase_vector_configured():
        raw_chunks = supabase_search(query, k=k)

    else:
        vectorstore = _get_chroma_vectorstore()
        results = vectorstore.similarity_search_with_score(query, k=k)

        raw_chunks = []
        for doc, distance in results:
            # Chroma devuelve distancia; convertimos a similaridad [0, 1]
            similarity = max(0.0, round(1.0 - float(distance), 4))
            raw_chunks.append({
                "content": doc.page_content,
                "source": doc.metadata.get("source", "desconocido"),
                "score": similarity,
            })

    all_scores = [chunk.get("score", 0.0) for chunk in raw_chunks]
    accepted = [
        chunk for chunk in raw_chunks
        if chunk.get("score", 0.0) >= RELEVANCE_THRESHOLD
    ]
    discarded = len(raw_chunks) - len(accepted)

    return _SearchResult(accepted, retrieval_scores=all_scores, discarded=discarded)
