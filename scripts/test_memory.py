"""Script de prueba: memoria conversacional short-term."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.providers import get_llm
from src.memory.short_term import ChatMemory


def main():
    # 1. Crear la memoria y el LLM
    memory = ChatMemory(max_messages=10)
    llm = get_llm()

    # 2. Simular una conversacion de varios turnos
    #    El LLM necesita el historial para entender referencias
    #    como "eso", "el primero", "cuanto cuesta", etc.

    mensajes_usuario = [
        "Me llamo Sebastian y trabajo en el departamento de IT.",
        "¿Como se llama mi departamento? (responde en una palabra)",
    ]

    for mensaje in mensajes_usuario:
        print(f"Usuario: {mensaje}")

        # 3. Guardar el mensaje del usuario en memoria
        memory.add_user_message(mensaje)

        # 4. Enviar al LLM TODO el historial (no solo el ultimo mensaje)
        #    Asi el LLM tiene contexto de lo que se dijo antes
        historial = memory.get_messages()
        print(f"  [Enviando {len(historial)} mensajes al LLM]")

        respuesta = llm.invoke(historial)

        # 5. Guardar la respuesta del LLM en memoria tambien
        #    Para que el proximo turno tenga tanto el mensaje como la respuesta
        memory.add_ai_message(respuesta.content)

        print(f"LLM: {respuesta.content}")
        print(f"  [Tokens: {respuesta.usage_metadata}]")
        print()

    # 6. Mostrar el historial completo guardado en memoria
    print("=" * 40)
    print("Historial completo en memoria:")
    print("=" * 40)
    for i, msg in enumerate(memory.get_messages()):
        # type(msg).__name__ nos dice si es HumanMessage, AIMessage, etc.
        rol = type(msg).__name__
        print(f"  [{i}] {rol}: {msg.content[:60]}...")


if __name__ == "__main__":
    main()
