"""Métricas RAG estilo RAGAS (simplificado).

Evalúa la calidad del retrieval y generation:
  - Faithfulness: ¿la respuesta está basada en las fuentes o alucina?
  - Answer relevance: ¿la respuesta aborda la pregunta?
  - Context precision: ¿los chunks recuperados son relevantes?

Implementación simplificada: usa el LLM como juez para cada métrica.
RAGAS real usa NLI (Natural Language Inference) para faithfulness,
pero el principio es el mismo.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.providers import get_llm
from src.rag.retriever import search


class FaithfulnessScore(BaseModel):
    """¿La respuesta está basada en las fuentes?"""
    score: float = Field(description="0.0 a 1.0 — 1.0 = totalmente fiel a las fuentes")
    claims_not_supported: list[str] = Field(
        description="Lista de afirmaciones en la respuesta que NO están en las fuentes",
        default_factory=list,
    )


class AnswerRelevanceScore(BaseModel):
    """¿La respuesta aborda la pregunta?"""
    score: float = Field(description="0.0 a 1.0 — 1.0 = totalmente relevante")
    razon: str = Field(description="Razón breve")


class ContextPrecisionScore(BaseModel):
    """¿Los chunks recuperados son relevantes para la pregunta?"""
    score: float = Field(description="0.0 a 1.0 — 1.0 = todos los chunks son relevantes")
    chunks_relevantes: int = Field(description="Número de chunks relevantes de los recuperados")
    chunks_totales: int = Field(description="Número total de chunks recuperados")


FAITHFULNESS_PROMPT = """Evaluas si una respuesta es fiel a las fuentes proporcionadas.

Fuentes (contexto recuperado):
{contexto}

Pregunta: {pregunta}
Respuesta del agente: {respuesta}

Instrucciones:
1. Extrae cada afirmación factual de la respuesta.
2. Verifica si cada afirmación está respaldada por las fuentes.
3. Si todas están respaldadas → score 1.0
4. Si ninguna está respaldada → score 0.0
5. Score intermedio según proporción.

Lista las afirmaciones que NO están respaldadas por las fuentes (alucinaciones)."""


RELEVANCE_PROMPT = """Evaluas si una respuesta aborda directamente la pregunta del usuario.

Pregunta: {pregunta}
Respuesta: {respuesta}

Instrucciones:
1. ¿La respuesta aborda la pregunta directamente?
2. ¿La información es útil para el usuario?
3. ¿La respuesta es clara y concisa?

Score 1.0 = respuesta perfecta para la pregunta.
Score 0.0 = no responde la pregunta en absoluto."""


CONTEXT_PRECISION_PROMPT = """Evaluas si los chunks recuperados son relevantes para la pregunta.

Pregunta: {pregunta}

Chunks recuperados:
{chunks}

Instrucciones:
1. Para cada chunk, determina si contiene información relevante para responder la pregunta.
2. Cuenta cuántos son relevantes.
3. Score = relevantes / totales."""


def evaluate_faithfulness(pregunta: str, respuesta: str, fuentes: list[dict]) -> FaithfulnessScore:
    """Evalúa si la respuesta es fiel a las fuentes (no alucina)."""
    llm = get_llm(temperature=0)
    llm_estructurado = llm.with_structured_output(FaithfulnessScore)

    # Construir contexto a partir de las fuentes
    contexto = ""
    for i, fuente in enumerate(fuentes):
        contexto += f"\n--- Fuente {i+1} ({fuente.get('source', 'desconocido')}) ---\n"
        contexto += fuente.get("content", fuente.get("text", str(fuente)))

    if not contexto.strip():
        contexto = "(Sin fuentes recuperadas)"

    prompt = FAITHFULNESS_PROMPT.format(
        contexto=contexto,
        pregunta=pregunta,
        respuesta=respuesta,
    )

    return llm_estructurado.invoke([
        SystemMessage(content="Eres un evaluador experto de sistemas RAG."),
        HumanMessage(content=prompt),
    ])


def evaluate_answer_relevance(pregunta: str, respuesta: str) -> AnswerRelevanceScore:
    """Evalúa si la respuesta aborda la pregunta."""
    llm = get_llm(temperature=0)
    llm_estructurado = llm.with_structured_output(AnswerRelevanceScore)

    prompt = RELEVANCE_PROMPT.format(pregunta=pregunta, respuesta=respuesta)

    return llm_estructurado.invoke([
        SystemMessage(content="Eres un evaluador experto de sistemas RAG."),
        HumanMessage(content=prompt),
    ])


def evaluate_context_precision(pregunta: str, k: int = 3) -> ContextPrecisionScore:
    """Evalúa si los chunks recuperados son relevantes para la pregunta."""
    llm = get_llm(temperature=0)
    llm_estructurado = llm.with_structured_output(ContextPrecisionScore)

    # Recuperar chunks
    results = search(pregunta, k=k)

    chunks_text = ""
    for i, doc in enumerate(results):
        score = doc.get("score", 0.0)
        content = doc.get("content", doc.get("text", str(doc)))
        chunks_text += f"\n--- Chunk {i+1} (score: {score:.4f}) ---\n"
        chunks_text += content

    if not chunks_text.strip():
        chunks_text = "(No se recuperaron chunks)"

    prompt = CONTEXT_PRECISION_PROMPT.format(pregunta=pregunta, chunks=chunks_text)

    result = llm_estructurado.invoke([
        SystemMessage(content="Eres un evaluador experto de sistemas RAG."),
        HumanMessage(content=prompt),
    ])

    # Asegurar que chunks_totales sea correcto
    result.chunks_totales = len(results)
    return result


def evaluate_rag(pregunta: str, respuesta: str, fuentes: list[dict]) -> dict:
    """Ejecuta todas las métricas RAG para una pregunta.

    Returns:
        Diccionario con faithfulness, answer_relevance, y context_precision.
    """
    faithfulness = evaluate_faithfulness(pregunta, respuesta, fuentes)
    relevance = evaluate_answer_relevance(pregunta, respuesta)
    precision = evaluate_context_precision(pregunta)

    return {
        "faithfulness": faithfulness.score,
        "faithfulness_claims": faithfulness.claims_not_supported,
        "answer_relevance": relevance.score,
        "answer_relevance_reason": relevance.razon,
        "context_precision": precision.score,
        "chunks_relevantes": precision.chunks_relevantes,
        "chunks_totales": precision.chunks_totales,
    }
