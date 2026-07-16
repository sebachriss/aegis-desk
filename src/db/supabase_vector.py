"""Vector store en Supabase Postgres con pgvector.

Usa la tabla `document_embeddings` creada por `scripts/migrate_postgres.py`.
Se activa automaticamente cuando `DATABASE_URL` esta configurado y no hay Pinecone.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.config import get_settings
from src.db.postgres_utils import get_postgres_connection
from src.rag.embeddings import EMBEDDING_MODEL, LocalEmbeddings

if TYPE_CHECKING:
    from langchain_core.documents import Document


def is_supabase_vector_configured() -> bool:
    settings = get_settings()
    return bool(settings.database_url)


def _embedding_to_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(v) for v in embedding) + "]"


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
    """Busca los k chunks mas relevantes usando cosine distance (<=>)."""
    embeddings = LocalEmbeddings(EMBEDDING_MODEL)
    query_emb = embeddings.embed_query(query)
    emb_literal = _embedding_to_literal(query_emb)

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, source, metadata,
                       embedding <=> %s::vector AS distance
                FROM document_embeddings
                ORDER BY distance
                LIMIT %s
                """,
                (emb_literal, k),
            )
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description or []]
            results = []
            for row in rows:
                d = dict(zip(cols, row))
                distance = d.get("distance") or 0.0
                # cosine distance: 0 = identico, 2 = opuesto
                score = max(0.0, round(1.0 - float(distance), 4))
                results.append({
                    "content": d["content"],
                    "source": d["source"],
                    "metadata": d.get("metadata") or {},
                    "score": score,
                })
            return results
