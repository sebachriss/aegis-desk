"""Test de latencia Groq vs DeepInfra para supervisor y crítico."""

import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.providers import get_fast_llm, get_llm


class Clasificacion(BaseModel):
    intencion: Literal["rag", "datos", "accion", "chat"]
    confidence: float


def main():
    print("=== GROQ vs DEEPINFRA ===")

    # Groq
    llm_groq = get_fast_llm()
    llm_groq_s = llm_groq.with_structured_output(Clasificacion, method="function_calling")

    start = time.time()
    r1 = llm_groq_s.invoke([
        SystemMessage(content="Clasifica: rag, datos, accion, chat"),
        HumanMessage(content="cuantos empleados hay?"),
    ])
    e1 = time.time() - start
    print(f"Groq: {r1.intencion}/{r1.confidence} in {e1:.2f}s")

    # DeepInfra
    llm_di = get_llm(temperature=0, max_tokens=256)
    llm_di_s = llm_di.with_structured_output(Clasificacion)

    start = time.time()
    r2 = llm_di_s.invoke([
        SystemMessage(content="Clasifica: rag, datos, accion, chat"),
        HumanMessage(content="cuantos empleados hay?"),
    ])
    e2 = time.time() - start
    print(f"DeepInfra: {r2.intencion}/{r2.confidence} in {e2:.2f}s")

    print(f"Groq es {e2 / e1:.1f}x mas rapido")


if __name__ == "__main__":
    main()
