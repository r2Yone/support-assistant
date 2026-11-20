"""Enrutamiento por regla: qué modelo responde cada pregunta (ADR 0008).

Una regla en código, no otro modelo: ``MODEL_LARGE`` si el enrutamiento está apagado,
si la pregunta es larga o si contiene una palabra clave que pide razonar o indica un
problema que se repite; ``MODEL_SMALL`` en cualquier otro caso.
"""

from dataclasses import dataclass

from app.knowledge_base import tokenize

ROUTING_DISABLED = "routing_disabled"
LONG_QUESTION = "long_question"
KEYWORD_PREFIX = "keyword:"
DEFAULT_ROUTE = "default"
LARGE_MODEL_KEYWORDS = ("por qué", "explica", "varios", "todos", "otra vez", "sigue")


@dataclass(frozen=True)
class Route:
    """El modelo elegido y por qué.

    :param model: Nombre del modelo.
    :type model: str
    :param reason: ``routing_disabled``, ``long_question``, ``keyword:<palabra>`` o
        ``default``.
    :type reason: str
    """

    model: str
    reason: str


def contains_phrase(words, phrase):
    """Indica si una secuencia de palabras aparece completa y seguida en otra.

    :param words: Palabras normalizadas de la pregunta.
    :type words: list[str]
    :param phrase: Palabras normalizadas de la frase buscada.
    :type phrase: tuple[str, ...]
    :return: ``True`` si ``phrase`` aparece en ``words`` como palabras completas.
    :rtype: bool
    """
    size = len(phrase)
    return any(
        tuple(words[index : index + size]) == phrase
        for index in range(len(words) - size + 1)
    )


class Router:
    """Elige el modelo de cada pregunta.

    :param enabled: ``ROUTING``; apagado, siempre se usa el modelo capaz.
    :type enabled: bool
    :param max_chars: ``ROUTER_MAX_CHARS``; preguntas más largas van al modelo capaz.
    :type max_chars: int
    :param small: Nombre del modelo barato (``MODEL_SMALL``).
    :type small: str
    :param large: Nombre del modelo capaz (``MODEL_LARGE``).
    :type large: str
    """

    def __init__(self, enabled, max_chars, small, large):
        self._enabled = enabled
        self._max_chars = max_chars
        self._small = small
        self._large = large
        # Se compara sin mayúsculas ni acentos, como palabras completas.
        self._keywords = [
            (keyword, tuple(tokenize(keyword))) for keyword in LARGE_MODEL_KEYWORDS
        ]

    def choose(self, question):
        """Elige el modelo de una pregunta.

        :param question: Pregunta de esta petición (no el historial).
        :type question: str
        :return: El modelo y el motivo.
        :rtype: Route
        """
        if not self._enabled:
            return Route(self._large, ROUTING_DISABLED)
        if len(question) > self._max_chars:
            return Route(self._large, LONG_QUESTION)
        words = tokenize(question)
        for keyword, phrase in self._keywords:
            if contains_phrase(words, phrase):
                return Route(self._large, KEYWORD_PREFIX + keyword)
        return Route(self._small, DEFAULT_ROUTE)
