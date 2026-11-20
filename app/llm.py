"""Interfaz del modelo de lenguaje y el modelo simulado.

El agente solo conoce ``complete(messages)``: cambiar de modelo no toca al agente.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from app.knowledge_base import tokenize

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
SEARCH_TOOL = "search_knowledge_base"
ESCALATE_TOOL = "escalate_to_human"
GENERAL_CATEGORY = "General"
PERSON_WORDS = frozenset({"persona", "humano", "humana", "agente"})
MIN_PROBLEM_WORDS = 3
FAKE_MODEL_NAME = "fake"
GUIDE_ANSWER = (
    "Describe tu problema (por ejemplo: «no me puedo conectar a la VPN») y busco "
    "una solución. Si prefieres, pide hablar con una persona."
)


@dataclass(frozen=True)
class Completion:
    """Respuesta del modelo.

    :param text: Texto que devolvió el modelo (un objeto JSON).
    :type text: str
    :param input_tokens: Tokens de entrada que consumió la llamada.
    :type input_tokens: int
    :param output_tokens: Tokens de salida que produjo la llamada.
    :type output_tokens: int
    :param cached: Si la respuesta vino de la caché del gateway (no cuesta).
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    cached: bool = False


class ChatModel(Protocol):
    """Lo que el agente necesita de un modelo."""

    def complete(self, messages):
        """Responde a una conversación.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: list[dict]
        :return: El texto del modelo y sus tokens.
        :rtype: Completion
        """


def _tool_call(tool, **args):
    """Arma la petición de una herramienta.

    :param tool: Nombre de la herramienta.
    :type tool: str
    :return: ``{"tool": tool, "args": args}``.
    :rtype: dict
    """
    return {"tool": tool, "args": args}


def _article_answer(article):
    """Arma la respuesta con la solución de un artículo.

    :param article: Artículo devuelto por la búsqueda.
    :type article: dict
    :return: ``{"answer": ...}`` con el id, el título y la solución.
    :rtype: dict
    """
    return {
        "answer": "Encontré una solución en la base de conocimiento "
        f"({article.get('id')}, {article.get('title')}): {article.get('solution')} "
        "Si no se resuelve, pide hablar con una persona."
    }


def _react_to_tool_result(payload_text):
    """Decide qué hacer con el resultado de una herramienta.

    :param payload_text: Lo que sigue al prefijo del resultado de la herramienta.
    :type payload_text: str
    :return: La respuesta o la siguiente herramienta a pedir.
    :rtype: dict
    """
    try:
        payload = json.loads(payload_text)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return _tool_call(ESCALATE_TOOL, category=GENERAL_CATEGORY)
    if "team" in payload:
        return {"answer": f"Te comunico con {payload['team']}."}
    articles = payload.get("articles")
    if not isinstance(articles, list):
        return _tool_call(ESCALATE_TOOL, category=GENERAL_CATEGORY)
    if articles:
        return _article_answer(articles[0])
    if payload.get("category"):
        return _tool_call(ESCALATE_TOOL, category=payload["category"])
    return {"answer": GUIDE_ANSWER}


def decide(content):
    """Aplica las reglas del modelo simulado al último mensaje.

    :param content: Texto del último mensaje.
    :type content: str
    :return: La respuesta o la herramienta a pedir.
    :rtype: dict
    """
    if content.startswith(TOOL_RESULT_PREFIX):
        return _react_to_tool_result(content[len(TOOL_RESULT_PREFIX):])
    if PERSON_WORDS & set(tokenize(content)):
        return _tool_call(ESCALATE_TOOL, category=GENERAL_CATEGORY)
    if len(content.split()) < MIN_PROBLEM_WORDS:
        return {"answer": GUIDE_ANSWER}
    return _tool_call(SEARCH_TOOL, problem=content)


def count_words(text):
    """Cuenta palabras separadas por espacios (tokens aproximados).

    :param text: Texto a contar.
    :type text: str
    :return: Cantidad de palabras.
    :rtype: int
    """
    return len(str(text).split())


class FakeModel:
    """Modelo simulado: determinista y sin red (``MODEL_PROVIDER=fake``).

    Todos responden igual; el nombre solo sirve para cobrarlo con el precio de un
    modelo real y medir las palancas de costo sin gastar cuota.

    :param name: Nombre del modelo (``MODEL_SMALL`` o ``MODEL_LARGE``).
    :type name: str
    """

    # Proveedor que ven las trazas en ``ls_provider`` (ADR 0016).
    provider = FAKE_MODEL_NAME

    def __init__(self, name=FAKE_MODEL_NAME):
        self.name = name

    def complete(self, messages):
        """Responde con las reglas de la especificación sobre el último mensaje.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: list[dict]
        :return: Un objeto JSON en texto y los tokens contados por palabras.
        :rtype: Completion
        """
        last = str(messages[-1].get("content", "")) if messages else ""
        text = json.dumps(decide(last), ensure_ascii=False)
        input_tokens = sum(count_words(m.get("content", "")) for m in messages)
        return Completion(
            text=text, input_tokens=input_tokens, output_tokens=count_words(text)
        )
