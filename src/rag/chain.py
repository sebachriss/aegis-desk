"""Cadena RAG: une retriever + LLM para responder preguntas con documentos.

Flujo:
  1. Recibe la pregunta del usuario
  2. Busca chunks relevantes en Chroma (retriever)
  3. Valida que las fuentes sean de documentos conocidos
  4. Construye un prompt con los chunks + la pregunta
  5. Le pide al LLM que responda basandose en los chunks, con citas
"""

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.providers import get_llm
from src.rag.retriever import search
from src.security.pii_filter import filter_pii

# Prompt de sistema: le dice al LLM como comportarse
SYSTEM_PROMPT = """Eres un asistente de soporte interno de Aegis Corp.
Responde la pregunta del usuario basándote ÚNICAMENTE en los documentos proporcionados abajo.

Reglas:
1. Si la información está en los documentos, responde y cita la fuente entre paréntesis. Ej: (fuente: politica_rrhh.md)
2. Si la información NO está en los documentos, di: "No tengo información sobre eso en los documentos disponibles."
3. No inventes información. No uses conocimiento externo.
4. Responde de forma clara y concisa.

Documentos proporcionados:
{contexto}
"""

_DOCUMENTS_DIR = Path(__file__).parent / "documents"


def _load_allowed_sources() -> set[str]:
    """Carga los nombres de todos los documentos .md disponibles."""
    if not _DOCUMENTS_DIR.exists():
        return set()
    return {p.name for p in _DOCUMENTS_DIR.glob("*.md")}


# Fuentes permitidas en el contexto RAG (actualizado automáticamente con el corpus)
_ALLOWED_SOURCES = _load_allowed_sources()

_NO_INFO_ANSWER = "No tengo información suficiente para responder eso."


def _source_is_valid(source: str) -> bool:
    """Acepta fuentes .md conocidas (con o sin sección) o resultados de aegis.db."""
    if not isinstance(source, str):
        return False
    # La Fase 5 añade secciones: "doc.md § Sección"
    base = source.split(" § ")[0].split("/")[-1]
    if base in _ALLOWED_SOURCES:
        return True
    if source.startswith("aegis.db"):
        return True
    return False


def _formatear_chunks(chunks: list[dict]) -> str:
    """Convierte los chunks encontrados en texto para meter en el prompt.

    Cada chunk se formatea asi:
      [fuente: politica_rrhh.md]
      ...texto del chunk...

    El contenido se redacta para no inyectar PII en el prompt del LLM.
    """
    partes = []
    for i, chunk in enumerate(chunks, 1):
        redacted_content, _ = filter_pii(chunk.get("content", ""))
        partes.append(f"[{i}] Fuente: {chunk['source']}")
        partes.append(redacted_content)
        partes.append("")  # linea en blanco entre chunks

    return "\n".join(partes)


def rag_query(question: str, k: int = 3) -> dict:
    """Responde una pregunta usando RAG (retrieval + generation).

    Args:
        question: Pregunta del usuario.
        k: Cuantos chunks recuperar de Chroma.

    Returns:
        Diccionario con: answer (respuesta del LLM), sources (chunks usados),
        usage (metadata del LLM), retrieval_scores y discarded counts.
    """
    # 1. Buscar chunks relevantes
    chunks = search(question, k=k)

    # 2. Recuperar metadatos del retrieval
    retrieval_scores = getattr(chunks, "retrieval_scores", [c.get("score") for c in chunks])
    discarded = getattr(chunks, "discarded", 0)

    # 3. Validar fuentes: solo documentos .md conocidos o aegis.db
    valid_chunks = [c for c in chunks if _source_is_valid(c.get("source", ""))]
    discarded += len(chunks) - len(valid_chunks)

    # 4. Si no hay chunks válidos, no llamamos al LLM
    if not valid_chunks:
        return {
            "answer": _NO_INFO_ANSWER,
            "sources": [],
            "usage": None,
            "retrieval_scores": retrieval_scores,
            "discarded": discarded,
        }

    # 5. Formatear los chunks como texto para el prompt
    contexto = _formatear_chunks(valid_chunks)

    # 6. Construir los mensajes
    system_msg = SystemMessage(content=SYSTEM_PROMPT.format(contexto=contexto))
    user_msg = HumanMessage(content=question)

    # 7. Llamar al LLM
    llm = get_llm(temperature=0)
    response = llm.invoke([system_msg, user_msg])

    # 8. Redactar PII en la respuesta final
    answer_filtrada, _ = filter_pii(response.content)

    # Redactar PII en las fuentes devueltas para no exponer datos sensibles
    safe_chunks = []
    for chunk in valid_chunks:
        safe_content, _ = filter_pii(chunk.get("content", ""))
        safe_chunks.append({**chunk, "content": safe_content})

    return {
        "answer": answer_filtrada,
        "sources": safe_chunks,
        "usage": response.usage_metadata,
        "retrieval_scores": retrieval_scores,
        "discarded": discarded,
    }
