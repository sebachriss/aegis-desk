"""Test de structured output con Groq - json_mode vs function_calling."""

import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.providers import get_fast_llm


class Clasificacion(BaseModel):
    """Clasificacion de la intencion del mensaje del usuario."""
    intencion: Literal["rag", "datos", "accion", "chat"] = Field(
        description="Categoria del mensaje: rag, datos, accion, o chat"
    )
    confidence: float = Field(
        description="Confianza en la clasificacion, de 0.0 a 1.0"
    )


SYSTEM = """Eres el supervisor de Aegis Desk. Clasifica la intención del mensaje en: rag, datos, accion, o chat.

Responde solo con la clasificación en formato JSON. No respondas la pregunta del usuario.
"""


def main():
    llm = get_fast_llm()

    # Test 1: json_mode
    print("=== json_mode ===")
    llm_s = llm.with_structured_output(Clasificacion, method="json_mode")
    try:
        start = time.time()
        r = llm_s.invoke([SystemMessage(content=SYSTEM), HumanMessage(content="cuantos empleados hay?")])
        print(f"OK: {r.intencion}/{r.confidence} in {time.time()-start:.2f}s")
    except Exception as e:
        print(f"FAIL: {e}")

    # Test 2: function_calling
    print("\n=== function_calling ===")
    llm_s2 = llm.with_structured_output(Clasificacion, method="function_calling")
    try:
        start = time.time()
        r2 = llm_s2.invoke([SystemMessage(content=SYSTEM), HumanMessage(content="cuantos empleados hay?")])
        print(f"OK: {r2.intencion}/{r2.confidence} in {time.time()-start:.2f}s")
    except Exception as e:
        print(f"FAIL: {e}")

    # Test 3: function_calling con include_raw
    print("\n=== function_calling + include_raw ===")
    llm_s3 = llm.with_structured_output(Clasificacion, method="function_calling", include_raw=True)
    try:
        start = time.time()
        r3 = llm_s3.invoke([SystemMessage(content=SYSTEM), HumanMessage(content="cuantos empleados hay?")])
        print(f"OK: parsed={r3['parsed']}, raw={str(r3['raw'])[:200]} in {time.time()-start:.2f}s")
    except Exception as e:
        print(f"FAIL: {e}")


if __name__ == "__main__":
    main()
