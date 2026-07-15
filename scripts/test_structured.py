"""Script de prueba: structured outputs con Pydantic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field

from src.llm.providers import get_llm


# 1. Definir el "molde" de la respuesta que queremos
#    BaseModel de Pydantic: define campos con tipos.
#    El LLM tiene que rellenar exactamente esto.
class ClasificacionMensaje(BaseModel):
    """Clasificacion de la intencion de un mensaje de usuario."""

    intencion: str = Field(
        description="Categoria del mensaje: rag, datos, accion, o chat",
    )
    confianza: float = Field(
        description="Nivel de confianza de 0.0 a 1.0",
    )
    razon: str = Field(
        description="Razon breve de por que se eligio esa intencion",
    )


def main():
    # 2. Obtener el LLM base
    llm = get_llm(temperature=0)  # temperature=0 para respuestas mas deterministicas

    # 3. Envolver el LLM con structured output
    #    .with_structured_output() devuelve un nuevo LLM que:
    #    - Le dice al LLM el schema (los campos y tipos de ClasificacionMensaje)
    #    - Activa JSON mode en la API
    #    - Parsea la respuesta y devuelve un objeto ClasificacionMensaje (no texto)
    llm_estructurado = llm.with_structured_output(ClasificacionMensaje)

    # 4. Mensajes de prueba
    mensajes = [
        "¿Cual es la politica de vacaciones de la empresa?",
        "Cuantos tickets abiertos hay en el sistema?",
        "Crea un ticket de alta prioridad para el servidor caido",
        "Hola, que tal?",
    ]

    for mensaje in mensajes:
        print(f"Mensaje: {mensaje}")
        print("-" * 40)

        # 5. Invocar — el resultado es un objeto ClasificacionMensaje, no texto
        resultado = llm_estructurado.invoke(mensaje)

        # 6. Acceder a los campos directamente (no hay que parsear JSON a mano)
        print(f"  Intencion: {resultado.intencion}")
        print(f"  Confianza: {resultado.confianza}")
        print(f"  Razon:     {resultado.razon}")
        print()


if __name__ == "__main__":
    main()
