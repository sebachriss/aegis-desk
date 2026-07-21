"""Búsqueda léxica BM25 en memoria sobre el corpus de Aegis Desk.

Construye un índice BM25 a partir de los mismos chunks que se indexan en
Chroma/Supabase/Pinecone. Se carga de forma lazy (singleton) para no penalizar
el arranque de la API ni los tests.
"""

import unicodedata
from typing import TYPE_CHECKING

from nltk.stem.snowball import SnowballStemmer
from rank_bm25 import BM25Okapi

from src.rag.ingest import load_documents, split_documents

# Stemmer para español (también funciona razonablemente con inglés técnico)
_stemmer = SnowballStemmer("spanish")

# Stopwords simples para reducir ruido en BM25
_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las",
    "por", "un", "para", "con", "no", "una", "su", "al", "lo", "más", "o",
    "este", "ya", "pero", "sus", "le", "me", "mi", "es", "son", "fue", "era",
    "esto", "ese", "esa", "eso", "aquí", "allí", "cómo", "qué", "quién",
    "cuál", "cuándo", "dónde", "porqué", "cuánto", "the", "and", "or", "of",
    "to", "in", "is", "you", "that", "it", "he", "was", "for", "on", "are",
    "as", "with", "his", "they", "i", "at", "be", "this", "have", "from",
    "one", "had", "by", "word", "but", "not", "what", "all", "were", "we",
    "when", "your", "can", "said", "there", "use", "an", "each", "which",
    "she", "do", "how", "their", "if", "will", "up", "other", "about", "out",
    "many", "then", "them", "these", "so", "some", "her", "would", "make",
    "like", "into", "him", "time", "has", "two", "more", "go", "way", "could",
    "my", "than", "first", "been", "call", "who", "its", "now", "find", "long",
    "down", "day", "did", "get", "come", "made", "may", "part", "am", "has",
    "have", "do", "does", "did", "be", "being", "been", "was", "were",
}

if TYPE_CHECKING:
    from langchain_core.documents import Document


def _normalize(text: str) -> str:
    """Normalización básica en español: minúsculas, sin tildes, solo alfanum."""
    text = text.lower()
    text = "".join(
        c
        for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    # Reemplazar todo lo que no sea alfanumérico por espacio
    text = "".join(c if c.isalnum() else " " for c in text)
    return text


def _tokenize(text: str) -> list[str]:
    """Tokeniza y stemiza para BM25, reduciendo ruido de stopwords."""
    tokens = _normalize(text).split()
    return [
        _stemmer.stem(t)
        for t in tokens
        if t and t not in _STOPWORDS and not t.isdigit()
    ]


# Singleton del índice
_bm25_index: BM25Okapi | None = None
_index_chunks: list["Document"] = []
_content_to_id: dict[str, int] = {}


def _build_index() -> tuple[BM25Okapi, list["Document"]]:
    """Construye el índice BM25 desde los chunks de ingest."""
    global _bm25_index, _index_chunks, _content_to_id

    if _bm25_index is not None:
        return _bm25_index, _index_chunks

    # Usar los mismos chunks que la ingesta (con headers y filtro anti-inyección)
    documents = load_documents()
    chunks = split_documents(documents)

    tokenized_corpus = [_tokenize(chunk.page_content) for chunk in chunks]
    _bm25_index = BM25Okapi(tokenized_corpus)
    _index_chunks = chunks
    _content_to_id = {chunk.page_content: i for i, chunk in enumerate(chunks)}

    return _bm25_index, _index_chunks


def get_index_chunks() -> list["Document"]:
    """Devuelve los chunks usados por el índice BM25."""
    _build_index()
    return _index_chunks


def find_chunk_id_by_content(content: str) -> int | None:
    """Mapea el contenido de un chunk a su id entero en el índice BM25."""
    _build_index()
    return _content_to_id.get(content)


def search_lexical(query: str, k: int = 10) -> list[int]:
    """Busca los k chunks más relevantes por BM25.

    Returns:
        Lista de índices enteros ordenados por relevancia descendente.
    """
    bm25, _ = _build_index()
    tokens = _tokenize(query)
    if not tokens:
        return []

    scores = bm25.get_scores(tokens)
    # argsort descendente
    top_k = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    # Filtrar scores nulos (no hay coincidencia de términos)
    return [i for i in top_k if scores[i] > 0]


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Fusión RRF (Reciprocal Rank Fusion) de rankings de ids.

    Args:
        rankings: Lista de rankings, cada uno es una lista de ids ordenados
            de más a menos relevante.
        k: Constante de suavizado (default 60, estándar RRF).

    Returns:
        Lista de ids ordenados por score RRF descendente.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        seen: set[int] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    # Ordenar por score descendente; en empate, por aparición más temprana
    def _sort_key(doc_id: int) -> tuple[float, int]:
        # Buscamos la primera aparición del id en todos los rankings
        first_rank = float("inf")
        for ranking in rankings:
            try:
                first_rank = min(first_rank, ranking.index(doc_id) + 1)
            except ValueError:
                pass
        return (-scores[doc_id], first_rank)

    return sorted(scores.keys(), key=_sort_key)
