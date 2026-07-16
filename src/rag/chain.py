"""Cadena RAG: une retriever + LLM para responder preguntas con documentos.

Flujo:
  1. Recibe la pregunta del usuario
  2. Busca chunks relevantes en Chroma (retriever)
  3. Construye un prompt con los chunks + la pregunta
  4. Le pide al LLM que responda basandose en los chunks, con citas
"""

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


def _formatear_chunks(chunks: list[dict]) -> str:
    """Convierte los chunks encontrados en texto para meter en el prompt.

    Cada chunk se formatea asi:
      [fuente: politica_rrhh.md]
      ...texto del chunk...
    """
    partes = []
    for i, chunk in enumerate(chunks, 1):
        partes.append(f"[{i}] Fuente: {chunk['source']}")
        partes.append(chunk["content"])
        partes.append("")  # linea en blanco entre chunks

    return "\n".join(partes)


def rag_query(question: str, k: int = 3) -> dict:
    """Responde una pregunta usando RAG (retrieval + generation).

    Args:
        question: Pregunta del usuario.
        k: Cuantos chunks recuperar de Chroma.

    Returns:
        Diccionario con: answer (respuesta del LLM), sources (chunks usados).
    """
    # 1. Buscar chunks relevantes
    chunks = search(question, k=k)

    # 2. Formatear los chunks como texto para el prompt
    contexto = _formatear_chunks(chunks)

    # 3. Construir los mensajes
    #    SystemMessage: instrucciones + documentos
    #    HumanMessage: la pregunta del usuario
    system_msg = SystemMessage(content=SYSTEM_PROMPT.format(contexto=contexto))
    user_msg = HumanMessage(content=question)

    # 4. Llamar al LLM
    llm = get_llm(temperature=0)  # temperature=0 para respuestas mas factuales
    response = llm.invoke([system_msg, user_msg])

    # 5. Redactar PII en la respuesta final
    answer_filtrada, _ = filter_pii(response.content)

    return {
        "answer": answer_filtrada,
        "sources": chunks,
        "usage": response.usage_metadata,
    }
