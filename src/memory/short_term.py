"""Memoria conversacional de corto plazo (ventana deslizante).

Mantiene el historial de mensajes de una conversacion y lo entrega
en formato LangChain (HumanMessage, AIMessage) para enviar al LLM.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


class ChatMemory:
    """Historial de mensajes de una conversacion con ventana deslizante.

    Guarda los mensajes en orden y permite recuperar los ultimos N
    para no enviar todo el historial al LLM (ahorro de tokens).

    Attributes:
        messages: Lista de mensajes en formato LangChain.
        max_messages: Maximo de mensajes a devolver con get_messages().
    """

    def __init__(self, max_messages: int = 20):
        """Inicializa la memoria vacia.

        Args:
            max_messages: Cuantos mensajes devolver en get_messages().
                Si hay mas, se devuelven solo los ultimos N.
        """
        self.messages: list = []
        self.max_messages = max_messages

    def add_user_message(self, content: str) -> None:
        """Agrega un mensaje del usuario al historial."""
        self.messages.append(HumanMessage(content=content))

    def add_ai_message(self, content: str) -> None:
        """Agrega un mensaje del asistente (respuesta del LLM) al historial."""
        self.messages.append(AIMessage(content=content))

    def add_system_message(self, content: str) -> None:
        """Agrega un mensaje de sistema (instrucciones, contexto global)."""
        self.messages.append(SystemMessage(content=content))

    def get_messages(self) -> list:
        """Devuelve los ultimos N mensajes en formato LangChain.

        Si hay menos de max_messages, devuelve todos.
        Si hay mas, devuelve solo los ultimos max_messages.
        """
        return self.messages[-self.max_messages :]

    def clear(self) -> None:
        """Vacia el historial completamente."""
        self.messages = []
