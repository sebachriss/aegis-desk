"""Vector store en Supabase Postgres con pgvector.

Usa la tabla `document_embeddings` creada por `scripts/migrate_postgres.py`.
Se activa automaticamente cuando `DATABASE_URL` esta configurado y no hay Pinecone.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from src.config import get_settings
from src.db.postgres_utils import get_postgres_connection
from src.rag.embeddings import get_embeddings

if TYPE_CHECKING:
    from langchain_core.documents import Document


def is_supabase_vector_configured() -> bool:
    settings = get_settings()
    return bool(settings.database_url)


def _embedding_to_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(v) for v in embedding) + "]"


# Stopwords simples en español/inglés para búsqueda por palabras clave.
_KEYWORD_STOPWORDS = {
    "qué", "que", "cómo", "como", "sobre", "para", "por", "con", "del", "los",
    "las", "una", "unos", "unas", "el", "la", "de", "en", "y", "o", "a", "un",
    "es", "son", "está", "estan", "tengo", "tiene", "tienen", "hacer", "hace",
    "dice", "dicen", "donde", "dónde", "cuando", "cuándo", "cual", "cuál",
    "what", "how", "where", "when", "does", "have", "has", "the", "and", "for",
    "about", "with", "from", "this", "that", "are", "is", "do",
}


def _extract_search_terms(query: str) -> list[str]:
    """Extrae términos relevantes de la consulta para búsqueda por palabra clave."""
    terms = re.findall(r"\w+", query.lower())
    return [t for t in terms if len(t) > 3 and t not in _KEYWORD_STOPWORDS]


def upsert_documents(docs: list["Document"], embeddings: list[list[float]]) -> int:
    """Inserta o actualiza chunks con sus embeddings en Supabase Postgres."""
    if len(docs) != len(embeddings):
        raise ValueError("docs y embeddings deben tener la misma longitud")

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            for i, (doc, emb) in enumerate(zip(docs, embeddings)):
                doc_id = f"{doc.metadata.get('source', 'doc').replace('/', '_')}_{i}"
                metadata = json.dumps(doc.metadata, ensure_ascii=False)
                emb_literal = _embedding_to_literal(emb)
                cur.execute(
                    """
                    INSERT INTO document_embeddings (id, content, source, metadata, embedding)
                    VALUES (%s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        source = EXCLUDED.source,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """,
                    (doc_id, doc.page_content, doc.metadata.get("source", "desconocido"), metadata, emb_literal),
                )
        conn.commit()
    return len(docs)


def search(query: str, k: int = 3) -> list[dict]:
    """Busca los k chunks mas relevantes usando cosine distance (<=>) + keyword fallback.

    El keyword fallback ayuda a recuperar chunks que contienen palabras clave de la
    consulta pero que el retriever puramente vectorial podría omitir (por ejemplo,
    modelos no multilingües con términos en español).
    """
    embeddings = get_embeddings()
    query_emb = embeddings.embed_query(query)
    emb_literal = _embedding_to_literal(query_emb)

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            # 1) Búsqueda vectorial top 2*k
            cur.execute(
                """
                SELECT id, content, source, metadata,
                       embedding <=> %s::vector AS distance
                FROM document_embeddings
                ORDER BY distance
                LIMIT %s
                """,
                (emb_literal, k * 2),
            )
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description or []]
            by_id: dict[str, dict] = {}
            for row in rows:
                d = dict(zip(cols, row))
                distance = d.get("distance") or 0.0
                score = max(0.0, round(1.0 - float(distance), 4))
                by_id[d["id"]] = {
                    "content": d["content"],
                    "source": d["source"],
                    "metadata": d.get("metadata") or {},
                    "score": score,
                }

            # 2) Búsqueda por palabras clave (fallback) y merge
            terms = _extract_search_terms(query)
            if terms:
                like_clauses = " OR ".join(["content ILIKE %s"] * len(terms))
                params = (emb_literal,) + tuple(f"%{t}%" for t in terms) + (k * 2,)
                cur.execute(
                    f"""
                    SELECT id, content, source, metadata,
                           embedding <=> %s::vector AS distance
                    FROM document_embeddings
                    WHERE {like_clauses}
                    ORDER BY distance
                    LIMIT %s
                    """,
                    params,
                )
                kw_rows = cur.fetchall()
                cols_kw = [desc[0] for desc in cur.description or []]
                for row in kw_rows:
                    d = dict(zip(cols_kw, row))
                    doc_id = d["id"]
                    content_lower = d["content"].lower()
                    matched_terms = sum(1 for t in terms if t in content_lower)
                    distance = d.get("distance") or 0.0
                    score = max(0.0, round(1.0 - float(distance), 4))
                    # Boost por cada término clave encontrado en el contenido
                    keyword_score = min(1.0, score + 0.18 * matched_terms)
                    if doc_id in by_id:
                        by_id[doc_id]["score"] = max(by_id[doc_id]["score"], keyword_score)
                    else:
                        by_id[doc_id] = {
                            "content": d["content"],
                            "source": d["source"],
                            "metadata": d.get("metadata") or {},
                            "score": keyword_score,
                        }

            # 3) Ordenar por score descendente y devolver top k
            results = sorted(by_id.values(), key=lambda x: x["score"], reverse=True)[:k]
            return results
