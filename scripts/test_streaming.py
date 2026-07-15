"""Script de prueba: streaming de respuesta token por token."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage

from src.llm.providers import get_llm


def main():
    # 1. Pedir un LLM con streaming activado
    llm = get_llm(streaming=True)

    print(f"Modelo: {llm.model_name}")
    print("-" * 40)
    print("Enviando mensaje (streaming)...\n")

    # 2. Usar .stream() en vez de .invoke()
    #    .stream() devuelve un generador: no devuelve la respuesta completa,
    #    sino que entrega "chunks" (pedazos) uno por uno a medida que el LLM los genera.
    chunks = llm.stream([HumanMessage(content="Escribe un poema corto sobre la luna. Máximo 4 líneas.")])

    # 3. Recorrer los chunks e imprimir cada pedacito
    #    Cada chunk tiene .content con un fragmento de texto (1 a pocos tokens).
    #    end=""   → no saltar línea después de cada print (queremos texto continuo)
    #    flush=True → forzar a la terminal a mostrar el texto ya, sin esperarlo en buffer
    for chunk in chunks:
        print(chunk.content, end="", flush=True)

    # Salto de línea final al terminar
    print("\n\nStreaming completado.")


if __name__ == "__main__":
    main()
