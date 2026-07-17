"""Reporta qué backend vectorial está activo y cuántos documentos tiene.

Uso:
    .venv/bin/python scripts/check_vector_store.py
"""

from src.config import get_settings
from src.db.pinecone_store import is_pinecone_configured
from src.db.supabase_vector import is_supabase_vector_configured
from src.rag.ingest import CHROMA_DIR
from src.rag.retriever import _get_chroma_vectorstore


def main():
    settings = get_settings()
    print("=" * 50)
    print("  VECTOR STORE REPORT")
    print("=" * 50)
    print(f"  DATABASE_URL set: {bool(settings.database_url)}")
    print(f"  Pinecone configured: {is_pinecone_configured()}")
    print(f"  Supabase vector configured: {is_supabase_vector_configured()}")
    print(f"  Chroma directory exists: {CHROMA_DIR.exists()}")
    print()

    if is_pinecone_configured():
        print("  Active backend: Pinecone")
    elif is_supabase_vector_configured():
        print("  Active backend: Supabase pgvector")
        try:
            from src.db.postgres_utils import get_postgres_connection
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM document_embeddings")
                    count = cur.fetchone()[0]
                    print(f"  Document embeddings count: {count}")
        except Exception as e:
            print(f"  Could not query Supabase: {e}")
    else:
        print("  Active backend: Chroma local")
        try:
            vectorstore = _get_chroma_vectorstore()
            count = vectorstore._collection.count()
            print(f"  Document embeddings count: {count}")
        except Exception as e:
            print(f"  Could not query Chroma: {e}")

    print("=" * 50)


if __name__ == "__main__":
    main()
