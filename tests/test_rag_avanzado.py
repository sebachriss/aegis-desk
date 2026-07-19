"""Tests deterministas para RAG avanzado (Fase 3 y 4).

Usan Chroma/BM25 local y embeddings locales; no requieren red.
"""

import os
from unittest.mock import MagicMock

os.environ["DEEPINFRA_API_KEY"] = ""
os.environ["DATABASE_URL"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["SUPABASE_SERVICE_KEY"] = ""

# Limpiar cache de settings para forzar lectura de las variables anteriores
from src.config import get_settings

get_settings.cache_clear()

import pytest
from langchain_core.documents import Document

from src.rag import lexical, reranker


def _mock_settings(hybrid: bool = True, rerank: bool = False):
    """Crea un settings de prueba sin acceso a red."""
    from src.config import Settings

    return Settings(
        hybrid_search_enabled=hybrid,
        reranker_enabled=rerank,
        deepinfra_api_key="",
    )


class TestRRF:
    def test_rrf_fuse_single_ranking(self):
        result = lexical.rrf_fuse([[3, 1, 2]])
        assert result == [3, 1, 2]

    def test_rrf_fuse_two_rankings(self):
        # Doc 1 en top de ambos debería ganar
        result = lexical.rrf_fuse([[1, 2, 3], [3, 1, 4]])
        assert result[0] == 1
        assert set(result) == {1, 2, 3, 4}

    def test_rrf_fuse_empty_rankings(self):
        assert lexical.rrf_fuse([]) == []
        assert lexical.rrf_fuse([[], []]) == []

    def test_rrf_fuse_duplicates_ignored(self):
        result = lexical.rrf_fuse([[1, 1, 2]])
        assert result == [1, 2]

    def test_rrf_fuse_unordered_ids(self):
        result = lexical.rrf_fuse([[10, 20], [20, 30]])
        assert result[0] == 20
        assert set(result) == {10, 20, 30}


class TestBM25:
    def test_tokenize_normalizes_tildes(self):
        # El stemmer reduce a la raíz y elimina tildes
        assert "polit" in lexical._tokenize("Política")[0]
        assert "vacac" in lexical._tokenize("Vacaciones")[0]

    def test_tokenize_removes_punctuation(self):
        tokens = lexical._tokenize("¿Cómo solicito?")
        assert "com" in tokens[0]
        assert "solicit" in tokens[1]

    def test_search_lexical_finds_keyword(self):
        # Corpus controlado con 3 docs para que el IDF BM25 sea > 0
        old_index = lexical._bm25_index
        old_chunks = lexical._index_chunks
        old_content_map = lexical._content_to_id
        try:
            chunks = [
                Document(page_content="política de vacaciones", metadata={"source": "vacaciones.md"}),
                Document(page_content="manual de seguridad de equipos", metadata={"source": "manual.md"}),
                Document(page_content="beneficios y bienestar", metadata={"source": "beneficios.md"}),
            ]
            tokenized = [lexical._tokenize(c.page_content) for c in chunks]
            lexical._bm25_index = lexical.BM25Okapi(tokenized)
            lexical._index_chunks = chunks
            lexical._content_to_id = {c.page_content: i for i, c in enumerate(chunks)}

            result = lexical.search_lexical("vacaciones", k=3)
            assert 0 in result
        finally:
            lexical._bm25_index = old_index
            lexical._index_chunks = old_chunks
            lexical._content_to_id = old_content_map

    def test_search_lexical_no_match(self):
        old_index = lexical._bm25_index
        try:
            lexical._bm25_index = None
            assert lexical.search_lexical("xyz123 noexistente", k=10) == []
        finally:
            lexical._bm25_index = old_index


class TestReranker:
    def test_rerank_returns_sorted_scores(self, monkeypatch):
        fake_model = MagicMock()
        fake_model.predict.return_value = [0.5, 2.5, -1.0]
        monkeypatch.setattr(reranker, "_cross_encoder", fake_model)

        chunks = [
            Document(page_content="foo", metadata={}),
            Document(page_content="bar", metadata={}),
            Document(page_content="baz", metadata={}),
        ]
        result = reranker.rerank("query", chunks, top_k=2)
        assert len(result) == 2
        # Mayor score raw -> mayor sigmoid
        assert result[0][0] == 1
        assert result[0][1] >= result[1][1]

    def test_rerank_empty_chunks(self):
        assert reranker.rerank("query", []) == []


class TestRetrieverHybrid:
    def _fake_chunks(self):
        return [
            Document(page_content="vacaciones 22 días", metadata={"source": "vacaciones.md"}),
            Document(page_content="vacaciones proceso", metadata={"source": "vacaciones.md"}),
            Document(page_content="equipos uso", metadata={"source": "uso_equipos.md"}),
            Document(page_content="seguridad equipos", metadata={"source": "seguridad_informacion.md"}),
        ]

    def test_hybrid_search_returns_search_result_metadata(self, monkeypatch):
        import src.rag.retriever as retriever_module

        monkeypatch.setattr(retriever_module, "_dense_candidates", lambda query, k: [0, 1])
        monkeypatch.setattr(retriever_module.lexical, "search_lexical", lambda query, k: [1, 2])
        monkeypatch.setattr(retriever_module.lexical, "get_index_chunks", self._fake_chunks)
        monkeypatch.setattr(retriever_module, "get_settings", lambda: _mock_settings(hybrid=True, rerank=False))

        result = retriever_module.search("vacaciones", k=3)
        assert isinstance(result, list)
        assert len(result) <= 3
        assert hasattr(result, "retrieval_scores")
        assert hasattr(result, "discarded")

    def test_hybrid_search_respects_k(self, monkeypatch):
        import src.rag.retriever as retriever_module

        monkeypatch.setattr(retriever_module, "_dense_candidates", lambda query, k: [0, 1, 2, 3])
        monkeypatch.setattr(retriever_module.lexical, "search_lexical", lambda query, k: [3, 2, 1, 0])
        monkeypatch.setattr(retriever_module.lexical, "get_index_chunks", self._fake_chunks)
        monkeypatch.setattr(retriever_module, "get_settings", lambda: _mock_settings(hybrid=True, rerank=False))

        result = retriever_module.search("equipos", k=2)
        assert len(result) <= 2

    def test_hybrid_disabled_equals_dense(self, monkeypatch):
        # Con HYBRID desactivado no se usa BM25: el resultado debe seguir siendo
        # una lista de chunks válida (aunque potencialmente vacía por umbral).
        import src.rag.retriever as retriever_module

        fake_doc = Document(page_content="vacaciones 22 días", metadata={"source": "vacaciones.md"})
        fake_store = MagicMock()
        fake_store.similarity_search_with_score.return_value = [(fake_doc, 0.2)]
        monkeypatch.setattr(retriever_module, "_get_chroma_vectorstore", lambda: fake_store)
        monkeypatch.setattr(retriever_module, "get_settings", lambda: _mock_settings(hybrid=False, rerank=False))

        result = retriever_module.search("vacaciones", k=3)
        assert isinstance(result, list)
        assert len(result) == 1
