"""Retriever: busca chunks relevantes en la base de datos vectorial.

Soporta:
  - Dense: Chroma local, Pinecone y Supabase pgvector.
  - Hybrid: BM25 en memoria + dense con RRF (configurable vía
    HYBRID_SEARCH_ENABLED).

El modelo de embeddings se obtiene de `get_embeddings()` (DeepInfra o local
según `DEEPINFRA_API_KEY`).
"""

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.config import get_settings
from src.db.pinecone_store import is_pinecone_configured, search as pinecone_search
from src.db.supabase_vector import is_supabase_vector_configured, search as supabase_search
from src.rag.embeddings import get_embeddings
from src.rag.ingest import CHROMA_DIR
from src.rag import lexical

# Singleton del vectorstore (se carga una sola vez)
_vectorstore: Chroma | None = None

# Umbral de relevancia: chunks con score final menor son descartados
RELEVANCE_THRESHOLD = 0.3

# Constante RRF y número de candidatos por vía
RRF_K = 60
_CANDIDATES = 10


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
        collection_metadata={"hnsw:space": "cosine"},
    )

    return _vectorstore


def _dense_candidates(query: str, k: int = _CANDIDATES) -> list[int]:
    """Recupera candidatos dense y los convierte a ids enteros del índice BM25."""
    if is_pinecone_configured():
        raw_chunks = pinecone_search(query, k=k)
    elif is_supabase_vector_configured():
        raw_chunks = supabase_search(query, k=k)
    else:
        vectorstore = _get_chroma_vectorstore()
        results = vectorstore.similarity_search_with_score(query, k=k)

        raw_chunks = []
        for doc, distance in results:
            # Chroma con cosine distance: convertimos a similaridad [0, 1]
            similarity = max(0.0, round(1.0 - float(distance), 4))
            raw_chunks.append({
                "content": doc.page_content,
                "source": doc.metadata.get("source", "desconocido"),
                "score": similarity,
            })

    # Mapear cada chunk a su id entero en el índice léxico
    ids = []
    for chunk in raw_chunks:
        idx = lexical.find_chunk_id_by_content(chunk["content"])
        if idx is not None:
            ids.append(idx)
    return ids


def _chunk_to_result(chunk: "Document", score: float) -> dict:
    """Convierte un Document de langchain al dict usado por el retriever."""
    source = chunk.metadata.get("source", "desconocido")
    return {
        "content": chunk.page_content,
        "source": source,
        "score": round(score, 4),
    }


def _apply_reranker(query: str, candidates: list[dict]) -> list[dict]:
    """Placeholder para Fase 4; ahora retorna los candidatos sin cambios."""
    return candidates


def search(query: str, k: int = 3) -> list[dict]:
    """Busca los k chunks más relevantes para una pregunta.

    Si HYBRID_SEARCH_ENABLED es True, recupera _CANDIDATES resultados por la
    vía densa y la vía léxica (BM25), los fusiona con RRF, aplica el umbral
    de relevancia y devuelve los top-k.

    Si HYBRID_SEARCH_ENABLED es False, comportamiento dense-only original.
    """
    settings = get_settings()

    # Ruta híbrida
    if settings.hybrid_search_enabled:
        dense_ranking = _dense_candidates(query, k=_CANDIDATES)
        lexical_ranking = lexical.search_lexical(query, k=_CANDIDATES)

        # Calcular scores RRF manualmente. El orden importa: lexical primero
        # para que, en caso de empate, gane la vía léxica (más fiable para
        # términos exactos en español).
        scores: dict[int, float] = {}
        rank_by_id: dict[int, tuple[int, int]] = {}
        for source_rank, ranking in enumerate((lexical_ranking, dense_ranking), start=1):
            for rank, doc_id in enumerate(ranking, start=1):
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
                current = rank_by_id.get(doc_id, (999, 999))
                updated = list(current)
                updated[source_rank - 1] = rank
                rank_by_id[doc_id] = tuple(updated)

        # Normalizar scores a [0, 1] usando el máximo teórico posible
        num_rankings = sum(1 for r in (lexical_ranking, dense_ranking) if r)
        max_raw_score = num_rankings / (RRF_K + 1) if num_rankings else 1.0

        id_to_score = {
            doc_id: round(scores[doc_id] / max_raw_score, 4)
            for doc_id in scores
        }
        # Ordenar por score descendente; en empates, priorizar rank léxico y
        # luego rank denso (menor es mejor).
        sorted_ids = sorted(
            id_to_score.keys(),
            key=lambda i: (
                -id_to_score[i],
                rank_by_id.get(i, (999, 999))[0],
                rank_by_id.get(i, (999, 999))[1],
            ),
        )

        index_chunks = lexical.get_index_chunks()

        accepted_ids = [
            doc_id for doc_id in sorted_ids
            if id_to_score[doc_id] >= RELEVANCE_THRESHOLD
        ]
        discarded = len(sorted_ids) - len(accepted_ids)
        top_ids = accepted_ids[:k]

        top_chunks = [_chunk_to_result(index_chunks[i], id_to_score[i]) for i in top_ids]
        all_scores = [id_to_score[i] for i in sorted_ids]

        return _SearchResult(top_chunks, retrieval_scores=all_scores, discarded=discarded)

    # Ruta densa original
    if is_pinecone_configured():
        raw_chunks = pinecone_search(query, k=k)
    elif is_supabase_vector_configured():
        raw_chunks = supabase_search(query, k=k)
    else:
        vectorstore = _get_chroma_vectorstore()
        results = vectorstore.similarity_search_with_score(query, k=k)

        raw_chunks = []
        for doc, distance in results:
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
