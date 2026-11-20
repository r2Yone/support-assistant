"""Pruebas unitarias del modelo simulado (``MODEL_PROVIDER=fake``)."""

import json

import pytest

from app.llm import FakeModel

TOOL_RESULT = "Resultado de la herramienta: "
GUIDE = (
    "Describe tu problema (por ejemplo: «no me puedo conectar a la VPN») y busco "
    "una solución. Si prefieres, pide hablar con una persona."
)
ARTICLE = {
    "id": "KB-0001",
    "title": "Conectarse a la VPN corporativa",
    "category": "Red",
    "solution": "Abre el cliente de VPN.",
    "updated": "2026-08-12",
}


def _reply(content):
    """Lo que el modelo simulado contesta a un único mensaje ``user``.

    :param content: Texto del mensaje.
    :return: La respuesta del modelo ya interpretada como JSON.
    """
    completion = FakeModel().complete([{"role": "user", "content": content}])
    return json.loads(completion.text)


def _tool_result(payload):
    """Arma el mensaje de resultado de herramienta con un objeto JSON."""
    return TOOL_RESULT + json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            _tool_result({"category": "Red", "team": "Mesa de Redes"}),
            {"answer": "Te comunico con Mesa de Redes."},
        ),
        (
            _tool_result({"category": "Red", "articles": [ARTICLE]}),
            {
                "answer": "Encontré una solución en la base de conocimiento "
                "(KB-0001, Conectarse a la VPN corporativa): Abre el cliente de "
                "VPN. Si no se resuelve, pide hablar con una persona."
            },
        ),
        (
            _tool_result({"category": "Hardware", "articles": []}),
            {"tool": "escalate_to_human", "args": {"category": "Hardware"}},
        ),
        (
            _tool_result({"category": None, "articles": []}),
            {"answer": GUIDE},
        ),
        (
            TOOL_RESULT + "error: unknown tool",
            {"tool": "escalate_to_human", "args": {"category": "General"}},
        ),
    ],
    ids=["transfer", "article-found", "no-article", "no-category", "tool-error"],
)
def test_fake_model_reacts_to_tool_results(content, expected):
    assert _reply(content) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "Quiero hablar con una persona",
            {"tool": "escalate_to_human", "args": {"category": "General"}},
        ),
        ("agente", {"tool": "escalate_to_human", "args": {"category": "General"}}),
        ("Hola buenas", {"answer": GUIDE}),
        (
            "Mi laptop no enciende",
            {
                "tool": "search_knowledge_base",
                "args": {"problem": "Mi laptop no enciende"},
            },
        ),
    ],
    ids=["asks-for-person", "person-before-short", "too-short", "problem"],
)
def test_fake_model_routes_the_employee_message(content, expected):
    assert _reply(content) == expected


def test_fake_model_counts_tokens_as_words():
    messages = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Describe tu problema"},
        {"role": "user", "content": "Mi laptop no enciende"},
    ]
    completion = FakeModel().complete(messages)
    assert completion.input_tokens == 8
    assert completion.output_tokens == len(completion.text.split())
