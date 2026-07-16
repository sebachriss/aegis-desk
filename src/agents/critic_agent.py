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

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.state import AgentState
from src.llm.providers import get_fast_llm

MAX_RETRIES = 2


class EvaluacionCritico(BaseModel):
    """Evaluacion de la respuesta del worker."""

    confidence: float = Field(
        description="Confianza en que la respuesta es correcta y completa, de 0.0 a 1.0",
    )
    razon: str = Field(
        description="Razon breve de la evaluacion",
    )
    necesita_reintento: bool = Field(
        description="True si la respuesta no es buena y el worker deberia intentar de nuevo",
    )


SYSTEM_PROMPT = """Eres el agente crítico de Aegis Desk.
Tu trabajo es evaluar la respuesta que dio un worker a la pregunta del usuario.

Criterios:
1. ¿La respuesta aborda directamente la pregunta?
2. ¿Es factually correcta según las fuentes proporcionadas (si las hay)?
   - Una respuesta del tipo "No tengo información sobre eso en los documentos disponibles" es CORRECTA y ÚTIL cuando ninguna fuente contiene la respuesta exacta. No marques como incorrecta ni pidas reintento en ese caso.
3. ¿Es clara y útil para el usuario?

Si la respuesta es buena, confidence alta (>= 0.7) y necesita_reintento = False.
Si la respuesta es incompleta, incorrecta, o no responde la pregunta, confidence baja y necesita_reintento = True.

Responde en formato JSON con los campos: confidence, razon, necesita_reintento.
"""


def critic_node(state: AgentState) -> dict:
    """Nodo del grafo: evalúa la respuesta del worker.

    Lee state["query"] y state["respuesta"], las evalúa, y decide:
    - Si es buena: confidence alta, no necesita reintento.
    - Si es mala y hay retries disponibles: marcar para reintento.
    - Si es mala y no hay retries: marcar para revisión humana.
    """
    llm = get_fast_llm(model="llama-3.3-70b-versatile")
    llm_estructurado = llm.with_structured_output(EvaluacionCritico, method="function_calling")

    query = state["query"]
    respuesta = state["respuesta"]
    fuentes = state.get("fuentes", [])
    retries = state.get("retries", 0)

    # Construir contexto para el crítico
    fuentes_texto = ""
    if fuentes:
        fuentes_texto = "\n\nFuentes usadas:\n"
        for f in fuentes:
            fuentes_texto += f"- {f.get('source', 'desconocido')}\n"

    mensaje = f"""Pregunta del usuario: {query}

Respuesta del worker: {respuesta}
{fuentes_texto}

Evalúa esta respuesta."""

    result = llm_estructurado.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=mensaje),
    ])

    # Lógica de decisión
    confidence = result.confidence
    needs_retry = result.necesita_reintento and retries < MAX_RETRIES
    requires_human = result.necesita_reintento and retries >= MAX_RETRIES

    return {
        "confidence": confidence,
        "requires_human_review": requires_human,
        "retries": retries + 1 if needs_retry else retries,
    }
