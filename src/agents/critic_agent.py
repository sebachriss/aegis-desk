"""Agente Crítico: revisa la calidad de la respuesta del worker.

Evalúa:
  - ¿La respuesta responde la pregunta?
  - ¿Es factually correcta según las fuentes?
  - ¿Necesita revisión humana?

Decisión:
  - Si confidence >= 0.7: respuesta OK (devuelve al usuario)
  - Si confidence < 0.7 y retries < 2: pedir reintento (vuelve al worker)
  - Si confidence < 0.7 y retries >= 2: marcar para revisión humana
"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import get_settings
from src.llm.providers import get_llm
from src.agents.state import AgentState

MAX_RETRIES = 2

SYSTEM_PROMPT = """Eres el agente crítico de Aegis Desk.
Tienes acceso a la PREGUNTA del usuario, la RESPUESTA del worker y las FUENTES utilizadas (incluyendo el resultado crudo de la base de datos o los documentos RAG).

Tu trabajo es evaluar si la respuesta es correcta y útil.

Criterios:
1. ¿La respuesta aborda directamente la pregunta?
2. ¿Es factually correcta según las fuentes proporcionadas?
   - Si la fuente es una consulta SQL, la respuesta debe coincidir con los datos de la fuente.
   - Una respuesta del tipo "No tengo información sobre eso en los documentos disponibles" es CORRECTA cuando ninguna fuente contiene la respuesta.
3. ¿Es clara y útil para el usuario?

Responde ÚNICAMENTE con un JSON con esta estructura exacta (sin comentarios, sin Markdown, sin texto extra):
{
  "confidence": <float entre 0.0 y 1.0>,
  "razon": <string breve>
}
"""


def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta del LLM."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta")
    return json.loads(match.group())


def critic_node(state: AgentState) -> dict:
    """Nodo del grafo: evalúa la respuesta del worker."""
    settings = get_settings()
    # Usar el modelo principal de DeepInfra para mayor fiabilidad en la evaluación.
    llm = get_llm(
        provider="deepinfra",
        model=settings.deepinfra_model,
        temperature=0,
        max_tokens=256,
    )

    query = state["query"]
    respuesta = state["respuesta"]
    fuentes = state.get("fuentes", [])
    retries = state.get("retries", 0)

    fuentes_texto = ""
    if fuentes:
        fuentes_texto = "\n\nFuentes usadas:\n"
        for f in fuentes:
            source = f.get("source", "desconocido")
            content = f.get("content", "")
            if content:
                fuentes_texto += f"- {source}: {content}\n"
            else:
                fuentes_texto += f"- {source}\n"

    mensaje = f"""Pregunta del usuario: {query}

Respuesta del worker: {respuesta}
{fuentes_texto}

Evalúa esta respuesta y devuelve SOLO el JSON."""

    raw = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=mensaje)]).content

    try:
        result = _extract_json(raw)
    except Exception:
        return {
            "confidence": 0.0,
            "requires_human_review": False,
            "retries": retries + 1 if retries < MAX_RETRIES else retries,
        }

    confidence = float(result.get("confidence", 0.0))
    is_acceptable = confidence >= 0.7

    needs_retry = not is_acceptable and retries < MAX_RETRIES
    requires_human = not is_acceptable and retries >= MAX_RETRIES

    return {
        "confidence": confidence,
        "requires_human_review": requires_human,
        "retries": retries + 1 if needs_retry else retries,
    }
