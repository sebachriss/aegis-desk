"""Reranking con cross-encoder local para mejorar la precisión del retrieval.

El modelo se carga de forma lazy (singleton) para no penalizar el arranque de la
API ni los tests. El flag `reranker_enabled` en `src/config.py` lo activa.
"""

import math
from typing import TYPE_CHECKING

from sentence_transformers import CrossEncoder

if TYPE_CHECKING:
    from langchain_core.documents import Document

# Modelo de cross-encoder del ecosistema sentence-transformers.
# Se evaluó también mmarco-mMiniLMv2-L12-H384-v1 (multilingüe), pero en este
# corpus español/técnico obtuvo peor MRR (0.9107 vs 0.9226) y mayor latencia
# de carga (modelo ~471 MB vs ~86 MB). ms-marco-MiniLM funciona mejor con el
# fallback híbrido implementado en retriever.py.
_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Singleton del modelo (cargado bajo demanda)
_cross_encoder: CrossEncoder | None = None


def _get_cross_encoder() -> CrossEncoder:
    """Devuelve el cross-encoder, cargándolo la primera vez."""
    global _cross_encoder
    if _cross_encoder is None:
        _cross_encoder = CrossEncoder(_DEFAULT_MODEL)
    return _cross_encoder


def _sigmoid(x: float) -> float:
    """Aplica sigmoid a un score raw del cross-encoder."""
    # Evitar overflow con valores extremos
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def rerank(query: str, chunks: list["Document"], top_k: int = 10) -> list[tuple[int, float]]:
    """Reranking de chunks según el query.

    Args:
        query: Pregunta del usuario.
        chunks: Lista de Document (o dicts con "content") a rerankear.
        top_k: Número de resultados a devolver.

    Returns:
        Lista de tuplas (chunk_index, score_sigmoid) ordenadas por relevancia
        descendente. El score está en [0, 1].
    """
    if not chunks:
        return []

    model = _get_cross_encoder()

    pairs = []
    for chunk in chunks:
        if isinstance(chunk, dict):
            text = chunk.get("content", chunk.get("text", str(chunk)))
        else:
            text = chunk.page_content
        pairs.append([query, text])

    raw_scores = model.predict(pairs, show_progress_bar=False)

    # Sigmoid para llevar scores a [0, 1]
    scored = [
        (i, round(_sigmoid(float(raw_scores[i])), 4))
        for i in range(len(chunks))
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def reset_reranker() -> None:
    """Libera el cross-encoder cargado (útil para tests)."""
    global _cross_encoder
    _cross_encoder = None
