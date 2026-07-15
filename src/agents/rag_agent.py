"""RAG Agent: nodo del grafo que responde preguntas usando documentos.

Reutiliza la cadena RAG de Fase 2 (src/rag/chain.py).
Lee la pregunta del estado, busca en Chroma, responde con citas.
"""

from src.agents.state import AgentState
from src.rag.chain import rag_query


def rag_node(state: AgentState) -> dict:
    """Nodo del grafo: responde usando RAG (búsqueda en documentos).

    Lee state["query"], busca chunks relevantes, llama al LLM con contexto,
    y devuelve la respuesta + fuentes al estado.
    """
    query = state["query"]

    resultado = rag_query(query, k=3)

    return {
        "respuesta": resultado["answer"],
        "fuentes": resultado["sources"],
    }
