"""Script de prueba: primera llamada a DeepSeek-V4-Flash vía DeepInfra."""

import sys
from pathlib import Path

# Agregar la raíz del proyecto al path para poder importar src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage

from src.llm.providers import get_llm


def main():
    # 1. Obtener el LLM desde nuestra abstracción
    llm = get_llm()

    # 2. Enviar un mensaje simple
    print(f"Modelo: {llm.model_name}")
    print("-" * 40)
    print("Enviando mensaje...\n")

    response = llm.invoke([HumanMessage(content="Hola, ¿quién eres?")])

    # 3. Mostrar la respuesta
    print(f"Respuesta: {response.content}")
    print(f"\nTokens usados: {response.usage_metadata}")


if __name__ == "__main__":
    main()
