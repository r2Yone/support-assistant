"""Pruebas unitarias del agente con un modelo guionado."""

import json

import pytest

from app.agent import Agent
from app.costs import PriceTable
from app.llm import Completion
from app.routing import Router

TOOL_RESULT = "Resultado de la herramienta: "
SEARCH = "search_knowledge_base"
ESCALATE = "escalate_to_human"
SMALL = "small-model"
LARGE = "large-model"
HISTORY = [
    {"role": "user", "content": "Primer mensaje"},
    {"role": "assistant", "content": "Primera respuesta"},
    {"role": "user", "content": "Segundo mensaje"},
    {"role": "assistant", "content": "Segunda respuesta"},
]


def _call(tool, **args):
    """Texto JSON con el que el modelo pide una herramienta."""
    return json.dumps({"tool": tool, "args": args})


class CachedFirstModel:
    """Modelo guionado cuya primera llamada viene de la caché del gateway.

    :param replies: Textos que devuelve, uno por llamada.
    :type replies: str
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, _messages):
        """Devuelve la siguiente respuesta; solo la primera es ``cached``.

        :return: La respuesta con 10 tokens de entrada y 3 de salida.
        :rtype: Completion
        """
        self.calls += 1
        return Completion(
            text=self.replies.pop(0),
            input_tokens=10,
            output_tokens=3,
            cached=self.calls == 1,
        )


@pytest.mark.parametrize(
    "bad_reply",
    [
        "esto no es JSON",
        _call("delete_everything"),
        _call(SEARCH, problem=""),
        _call(SEARCH, problem="a" * 2001),
        _call(SEARCH),
        _call(ESCALATE, category="Red 5"),
        _call(ESCALATE, category="a" * 65),
    ],
    ids=[
        "invalid-json",
        "unknown-tool",
        "empty-problem",
        "too-long-problem",
        "missing-problem",
        "category-with-digits",
        "too-long-category",
    ],
)
def test_bad_model_output_is_reported_back_and_the_loop_continues(
    scripted_model, knowledge_base, bad_reply
):
    model = scripted_model(bad_reply, '{"answer": "Listo"}')
    agent = Agent(model, knowledge_base, max_steps=4, max_question_chars=2000)
    result = agent.run("Mi laptop no enciende", [])
    assert result.answer == "Listo"
    assert result.steps == 2
    assert isinstance(result.tools_used, list)
    assert not result.tools_used
    assert result.escalated is False
    feedback = model.calls[1][-1]
    assert feedback["role"] == "user"
    assert feedback["content"].startswith(TOOL_RESULT)
    assert "error" in feedback["content"].lower()


def test_escalation_ends_the_loop_in_the_same_step(scripted_model, knowledge_base):
    model = scripted_model(_call(ESCALATE, category="Red"))
    agent = Agent(model, knowledge_base, max_steps=4, max_question_chars=2000)
    result = agent.run("Quiero hablar con una persona", [])
    assert result.answer == "Te comunico con Mesa de Redes."
    assert result.steps == 1
    assert result.tools_used == [ESCALATE]
    assert result.escalated is True
    assert result.team == "Mesa de Redes"
    assert len(model.calls) == 1


def test_tool_result_and_history_reach_the_model_and_tokens_add_up(
    scripted_model, knowledge_base
):
    history = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Describe tu problema"},
    ]
    search = _call(SEARCH, problem="No me puedo conectar a la VPN")
    model = scripted_model(search, '{"answer": "Usa el cliente de VPN"}')
    agent = Agent(model, knowledge_base, max_steps=4, max_question_chars=2000)
    result = agent.run("No me puedo conectar a la VPN", history)
    first, second = model.calls
    assert first == history + [
        {"role": "user", "content": "No me puedo conectar a la VPN"}
    ]
    assert second[-2] == {"role": "assistant", "content": search}
    tool_output = json.loads(second[-1]["content"].removeprefix(TOOL_RESULT))
    assert tool_output["category"] == "Red"
    assert tool_output["articles"][0]["id"] == "KB-0001"
    assert (result.answer, result.steps, result.tools_used) == (
        "Usa el cliente de VPN",
        2,
        [SEARCH],
    )
    assert (result.input_tokens, result.output_tokens) == (20, 6)
    assert result.team is None


def test_each_way_to_end_reports_its_outcome_article_and_stop(
    scripted_model, knowledge_base
):
    vpn_search = _call(SEARCH, problem="No me puedo conectar a la VPN")
    no_match = _call(SEARCH, problem="Que clima hace hoy en Monterrey")
    guide = '{"answer": "Describe tu problema"}'
    cases = [
        ((vpn_search, '{"answer": "Usa el cliente de VPN"}'), 4, "solved", "KB-0001"),
        ((no_match, guide), 4, "needs_detail", None),
        ((guide,), 4, "needs_detail", None),
        ((_call(ESCALATE, category="Red"),), 4, "escalated", None),
        ((vpn_search,), 1, "incomplete", None),
    ]
    for replies, max_steps, outcome, article_id in cases:
        model = scripted_model(*replies)
        agent = Agent(
            model, knowledge_base, max_steps=max_steps, max_question_chars=2000
        )
        result = agent.run("Necesito ayuda con mi equipo", [])
        assert (result.outcome, result.article_id) == (outcome, article_id)
        assert result.stopped is (outcome == "incomplete")


def test_each_executed_tool_is_audited_without_the_problem_text(
    scripted_model, knowledge_base
):
    problem = "No me puedo conectar a la VPN"
    model = scripted_model(
        _call(SEARCH, problem=""),
        _call(SEARCH, problem=problem),
        _call(ESCALATE, category="Red"),
    )
    audits = []
    agent = Agent(model, knowledge_base, max_steps=4, max_question_chars=2000)
    agent.run(problem, [], on_tool_call=audits.append)
    assert [audit["tool"] for audit in audits] == [SEARCH, ESCALATE]
    search, escalation = audits[0], audits[-1]
    assert search["problem_chars"] == len(problem)
    assert search["category"] == "Red"
    assert "KB-0001" in search["article_ids"]
    assert (escalation["category"], escalation["team"]) == ("Red", "Mesa de Redes")
    assert problem not in json.dumps(audits, ensure_ascii=False)


@pytest.mark.parametrize(
    ("window", "kept"),
    [(0, 0), (2, 2), (10, 4)],
    ids=["no-history", "last-two", "window-larger-than-history"],
)
def test_history_window_sends_only_the_last_messages(
    scripted_model, knowledge_base, window, kept
):
    model = scripted_model('{"answer": "Listo"}')
    agent = Agent(
        model,
        knowledge_base,
        max_steps=4,
        max_question_chars=2000,
        history_window=window,
    )
    agent.run("Mi laptop no enciende", [dict(m) for m in HISTORY])
    question = {"role": "user", "content": "Mi laptop no enciende"}
    expected = HISTORY[len(HISTORY) - kept :] + [question]
    assert model.calls[0] == expected


def test_the_router_picks_the_model_and_cached_calls_cost_nothing(
    scripted_model, knowledge_base, tmp_path
):
    prices_file = tmp_path / "model_prices.json"
    prices_file.write_text(
        json.dumps(
            {
                "models": {
                    SMALL: {"input": 1.0, "output": 2.0},
                    LARGE: {"input": 10.0, "output": 20.0},
                }
            }
        ),
        encoding="utf-8",
    )
    small = scripted_model('{"answer": "chico"}')
    large = CachedFirstModel(
        _call(SEARCH, problem="No me puedo conectar a la VPN"),
        '{"answer": "grande"}',
    )
    agent = Agent(
        small,
        knowledge_base,
        max_steps=4,
        max_question_chars=2000,
        models={SMALL: small, LARGE: large},
        router=Router(enabled=True, max_chars=80, small=SMALL, large=LARGE),
        prices=PriceTable.from_file(prices_file),
    )
    result = agent.run("Otra vez no me conecta la VPN", [])
    assert (result.answer, result.model, result.route) == (
        "grande",
        LARGE,
        "keyword:otra vez",
    )
    assert not small.calls
    assert result.cached_calls == 1
    assert result.cost_usd == pytest.approx((10 * 10.0 + 3 * 20.0) / 1_000_000)
    assert (result.input_tokens, result.output_tokens) == (20, 6)


def test_search_uses_the_question_words_when_the_model_rephrases_the_problem(
    scripted_model, knowledge_base
):
    question, rephrased = "No sé mi contraseña", "olvidé acceso"
    assert not knowledge_base.search(question)["articles"]
    assert not knowledge_base.search(rephrased)["articles"]
    model = scripted_model(
        _call(SEARCH, problem=rephrased), '{"answer": "Usa el portal"}'
    )
    audits = []
    agent = Agent(model, knowledge_base, max_steps=4, max_question_chars=2000)
    result = agent.run(question, [], on_tool_call=audits.append)
    assert audits[0]["article_ids"][0] == "KB-0003"
    assert audits[0]["problem_chars"] == len(rephrased)
    assert (result.outcome, result.article_id) == ("solved", "KB-0003")
