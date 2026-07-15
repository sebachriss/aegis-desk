"""Script de prueba: RAG — preguntas respondidas con documentos de la empresa."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.observability.metrics import print_metrics, track_llm_call
from src.rag.chain import rag_query


def main():
    preguntas = [
        "¿Cuantos dias de vacaciones tengo?",
        "¿Como reseteo mi contraseña?",
        "¿Puedo traer a mi mascota a la oficina?",
        "¿Cual es el salario del CEO?",  # no esta en los docs — debe decir que no sabe
    ]

    for pregunta in preguntas:
        print(f"\n{'=' * 50}")
        print(f"Pregunta: {pregunta}")
        print(f"{'=' * 50}")

        inicio = time.time()
        resultado = rag_query(pregunta)
        elapsed = time.time() - inicio

        # Mostrar fuentes encontradas
        print(f"\nFuentes encontradas ({len(resultado['sources'])}):")
        for chunk in resultado["sources"]:
            print(f"  - {chunk['source']} (score: {chunk['score']})")
            print(f"    {chunk['content'][:80]}...")

        # Mostrar respuesta
        print(f"\nRespuesta:\n  {resultado['answer']}")

        # Mostrar metricas
        print()
        print_metrics(track_llm_call(resultado["usage"], elapsed))


if __name__ == "__main__":
    main()
