"""Pruebas unitarias de la base de conocimiento.

Cubren la normalización, la clasificación, la búsqueda y la transferencia.
"""

import json

import pytest

from app.knowledge_base import KnowledgeBase, normalize, tokenize


def _article(article_id, category, keywords, status="vigente"):
    """Arma un artículo de prueba.

    :param article_id: Identificador del artículo.
    :param category: Categoría del artículo.
    :param keywords: Palabras clave.
    :param status: ``vigente`` u ``obsoleto``.
    :return: El artículo como diccionario.
    """
    return {
        "id": article_id,
        "title": f"Title {article_id}",
        "category": category,
        "keywords": keywords,
        "solution": f"Solution {article_id}",
        "status": status,
        "updated": "2026-01-01",
    }


SAMPLE = {
    "general_team": "General Desk",
    "categories": [
        {"name": "Alpha", "team": "Alpha Team", "keywords": ["red", "blue"]},
        {"name": "Beta", "team": "Beta Team", "keywords": ["green", "yellow"]},
    ],
    "articles": [
        _article("A-1", "Alpha", ["red", "blue", "cat"]),
        _article("A-2", "Beta", ["red", "blue", "dog"]),
        _article("A-3", "Beta", ["red", "blue", "cat", "dog"]),
        _article("A-4", "Alpha", ["red", "blue", "cat", "dog", "owl"], "obsoleto"),
        _article("G-1", "Beta", ["owl", "fox"]),
    ],
}


def _ids(result):
    """Los ids de los artículos de un resultado de búsqueda."""
    return [article["id"] for article in result["articles"]]


def test_text_is_compared_in_lowercase_without_accents():
    assert normalize("Conexión") == "conexion"
    words = set(tokenize("Wi-Fi sin CONEXIÓN 5G"))
    assert words == {"wi", "fi", "sin", "conexion", "5g"}


@pytest.mark.parametrize(
    ("problem", "category"),
    [
        ("red blue green", "Alpha"),
        ("green red", "Alpha"),
        ("owl fox", "Beta"),
        ("weather today", None),
    ],
    ids=["most-keywords", "tie-goes-to-first", "best-article", "nothing-matches"],
)
def test_problem_is_classified_into_the_category_with_most_keywords(problem, category):
    knowledge = KnowledgeBase(SAMPLE, min_score=2, max_results=2)
    assert knowledge.search(problem)["category"] == category


def test_search_returns_only_current_articles_ranked_and_capped():
    # A-4 tendría el mejor puntaje, pero es obsoleto: no existe para la búsqueda.
    problem = "RED blue cat dog owl"
    capped = KnowledgeBase(SAMPLE, min_score=2, max_results=2).search(problem)
    assert _ids(capped) == ["A-3", "A-1"]
    wide = KnowledgeBase(SAMPLE, min_score=2, max_results=5).search(problem)
    assert _ids(wide) == ["A-3", "A-1", "A-2"]
    fields = {"id", "title", "category", "solution", "updated"}
    assert set(wide["articles"][0]) == fields
    strict = KnowledgeBase(SAMPLE, min_score=4, max_results=5).search(problem)
    assert _ids(strict) == ["A-3"]


@pytest.mark.parametrize(
    ("category", "team"),
    [
        ("Red", "Mesa de Redes"),
        ("General", "Mesa de Servicio General"),
        ("Categoria Inventada", "Mesa de Servicio General"),
    ],
)
def test_escalation_names_the_team_of_the_category(knowledge_base, category, team):
    assert knowledge_base.escalate(category)["team"] == team


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"categories": [], "articles": []}),
        json.dumps({**SAMPLE, "articles": [{"id": "A-9", "title": "No solution"}]}),
        json.dumps({**SAMPLE, "articles": [_article("A-9", "Alpha", ["x"], "draft")]}),
    ],
    ids=["not-json", "missing-general-team", "incomplete-article", "unknown-status"],
)
def test_malformed_knowledge_base_file_is_rejected(tmp_path, content):
    path = tmp_path / "knowledge_base.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        KnowledgeBase.from_file(path, min_score=2, max_results=2)
