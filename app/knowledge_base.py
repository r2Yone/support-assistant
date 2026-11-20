"""Base de conocimiento: carga, búsqueda determinista y transferencia.

La búsqueda no usa red: compara palabras normalizadas (minúsculas y sin acentos)
del problema con las palabras clave de las categorías y de los artículos.
"""

import json
import re
import unicodedata
from pathlib import Path

CURRENT_STATUS = "vigente"
VALID_STATUSES = frozenset({"vigente", "obsoleto"})
GENERAL_CATEGORY = "General"
ARTICLE_FIELDS = (
    "id", "title", "category", "keywords", "solution", "status", "updated"
)
RESULT_FIELDS = ("id", "title", "category", "solution", "updated")
CATEGORY_FIELDS = ("name", "team", "keywords")
_WORD = re.compile(r"[^\W_]+")


class KnowledgeBaseError(ValueError):
    """La base de conocimiento no se pudo leer o no tiene la forma esperada."""


def normalize(text):
    """Pasa un texto a minúsculas y le quita los acentos.

    :param text: Texto original.
    :type text: str
    :return: El texto en minúsculas, sin marcas diacríticas.
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(text):
    """Separa un texto en palabras normalizadas.

    Una palabra es una secuencia de letras y dígitos (``Wi-Fi`` da ``wi`` y ``fi``).

    :param text: Texto original.
    :type text: str
    :return: Las palabras en el orden en que aparecen.
    :rtype: list[str]
    """
    return _WORD.findall(normalize(text))


def _keyword_set(keywords):
    """Normaliza una lista de palabras clave y quita repetidas.

    :param keywords: Palabras clave tal como vienen en el archivo.
    :type keywords: list[str]
    :return: Las palabras clave normalizadas.
    :rtype: frozenset[str]
    """
    return frozenset(normalize(keyword) for keyword in keywords)


def _require_text(value, where):
    """Comprueba que un valor sea texto no vacío.

    :param value: Valor a revisar.
    :type value: object
    :param where: Descripción del lugar, para el mensaje de error.
    :type where: str
    :raises KnowledgeBaseError: Si no es texto o está vacío.
    """
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeBaseError(f"{where} debe ser texto no vacío")


def _require_keywords(value, where):
    """Comprueba que un valor sea una lista de textos no vacíos.

    :param value: Valor a revisar.
    :type value: object
    :param where: Descripción del lugar, para el mensaje de error.
    :type where: str
    :raises KnowledgeBaseError: Si no es una lista de textos.
    """
    if not isinstance(value, list):
        raise KnowledgeBaseError(f"{where} debe ser una lista")
    for keyword in value:
        _require_text(keyword, where)


def _validate_entry(entry, fields, where):
    """Comprueba que una categoría o un artículo tenga todos sus campos.

    :param entry: La categoría o el artículo.
    :type entry: object
    :param fields: Campos obligatorios.
    :type fields: tuple[str, ...]
    :param where: Descripción del lugar, para el mensaje de error.
    :type where: str
    :raises KnowledgeBaseError: Si falta un campo o tiene un tipo inválido.
    """
    if not isinstance(entry, dict):
        raise KnowledgeBaseError(f"{where} debe ser un objeto")
    missing = [field for field in fields if field not in entry]
    if missing:
        raise KnowledgeBaseError(f"{where} no tiene {', '.join(missing)}")
    for field in fields:
        if field == "keywords":
            _require_keywords(entry[field], f"{where}.keywords")
        else:
            _require_text(entry[field], f"{where}.{field}")


def validate_data(data):
    """Comprueba la forma completa de la base de conocimiento.

    :param data: Contenido del archivo ya interpretado.
    :type data: object
    :raises KnowledgeBaseError: Si algo no tiene la forma descrita.
    """
    if not isinstance(data, dict):
        raise KnowledgeBaseError("la base de conocimiento debe ser un objeto")
    _require_text(data.get("general_team"), "general_team")
    for part in ("categories", "articles"):
        if not isinstance(data.get(part), list):
            raise KnowledgeBaseError(f"{part} debe ser una lista")
    for index, category in enumerate(data["categories"]):
        _validate_entry(category, CATEGORY_FIELDS, f"categories[{index}]")
    for index, article in enumerate(data["articles"]):
        _validate_entry(article, ARTICLE_FIELDS, f"articles[{index}]")
        if article["status"] not in VALID_STATUSES:
            raise KnowledgeBaseError(
                f"articles[{index}].status debe ser vigente u obsoleto"
            )


class KnowledgeBase:
    """Base de conocimiento de solo lectura.

    :param data: Contenido de ``knowledge_base.json`` ya interpretado.
    :type data: dict
    :param min_score: Palabras clave que deben coincidir para ofrecer un artículo.
    :type min_score: int
    :param max_results: Artículos que devuelve la búsqueda como máximo.
    :type max_results: int
    :raises KnowledgeBaseError: Si los datos o los límites son inválidos.
    """

    def __init__(self, data, min_score, max_results):
        validate_data(data)
        if min_score < 1 or max_results < 1:
            raise KnowledgeBaseError("min_score y max_results deben ser 1 o más")
        self._general_team = data["general_team"]
        self._min_score = min_score
        self._max_results = max_results
        self._categories = [
            (category, _keyword_set(category["keywords"]))
            for category in data["categories"]
        ]
        # Un artículo obsoleto es como si no existiera para la búsqueda.
        self._articles = [
            (article, _keyword_set(article["keywords"]))
            for article in data["articles"]
            if article["status"] == CURRENT_STATUS
        ]

    @classmethod
    def from_file(cls, path, min_score, max_results):
        """Carga la base de conocimiento desde un archivo JSON.

        :param path: Ruta del archivo.
        :type path: str or pathlib.Path
        :param min_score: Palabras clave que deben coincidir para ofrecer un artículo.
        :type min_score: int
        :param max_results: Artículos que devuelve la búsqueda como máximo.
        :type max_results: int
        :return: La base de conocimiento cargada.
        :rtype: KnowledgeBase
        :raises KnowledgeBaseError: Si el archivo no se puede leer o no tiene la forma
            descrita.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise KnowledgeBaseError(f"no se pudo leer {path}: {error}") from error
        return cls(data, min_score=min_score, max_results=max_results)

    def search(self, problem):
        """Clasifica el problema y busca artículos vigentes que lo resuelvan.

        :param problem: El problema con las palabras de la persona.
        :type problem: str
        :return: ``{"category": nombre o None, "articles": [...]}``.
        :rtype: dict
        """
        words = set(tokenize(problem))
        articles = self._rank_articles(words)
        category = self._classify(words)
        if category is None and articles:
            category = articles[0]["category"]
        return {
            "category": category,
            "articles": [
                {field: article[field] for field in RESULT_FIELDS}
                for article in articles
            ],
        }

    def escalate(self, category):
        """Indica qué equipo humano atiende una categoría.

        Una categoría que no existe, o ``General``, se atiende con el equipo general.

        :param category: Nombre de la categoría.
        :type category: str
        :return: ``{"category": nombre, "team": equipo}``.
        :rtype: dict
        """
        wanted = normalize(category.strip())
        for entry, _ in self._categories:
            if normalize(entry["name"]) == wanted:
                return {"category": entry["name"], "team": entry["team"]}
        return {"category": GENERAL_CATEGORY, "team": self._general_team}

    def _classify(self, words):
        """La categoría con más palabras clave presentes; en empate, la primera.

        :param words: Palabras normalizadas del problema.
        :type words: set[str]
        :return: El nombre de la categoría o ``None`` si ninguna coincide.
        :rtype: str or None
        """
        best_name, best_score = None, 0
        for category, keywords in self._categories:
            score = len(keywords & words)
            if score > best_score:
                best_name, best_score = category["name"], score
        return best_name

    def _rank_articles(self, words):
        """Los artículos vigentes con puntaje suficiente, de mayor a menor.

        :param words: Palabras normalizadas del problema.
        :type words: set[str]
        :return: Como máximo ``max_results`` artículos; el empate respeta el archivo.
        :rtype: list[dict]
        """
        scored = [
            (len(keywords & words), article) for article, keywords in self._articles
        ]
        eligible = [pair for pair in scored if pair[0] >= self._min_score]
        # sorted es estable: en empate se conserva el orden del archivo.
        eligible = sorted(eligible, key=lambda pair: pair[0], reverse=True)
        return [article for _, article in eligible[: self._max_results]]
