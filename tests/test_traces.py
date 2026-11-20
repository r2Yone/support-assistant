"""Pruebas unitarias de lo que el agente y los modelos agregan a las trazas.

Las trazas van al módulo ``langsmith`` sustituto de ``conftest.py``: nunca a la red.
"""

import inspect

import pytest

from app import tracing
from app.agent import Agent
from app.config import load_settings
from app.gateway import GatewayModel, ModelUnavailable
from app.llm import FakeModel

LAPTOP_PROBLEM = "Mi laptop no enciende"
PERSON_REQUEST = "Quiero hablar con una persona"
MODEL_NAME = "fake-small"


class UnavailableModel:
    """Modelo cuyo proveedor nunca responde."""

    def complete(self, _messages):
        """Falla como el gateway cuando el proveedor responde 500.

        :raises ModelUnavailable: Siempre.
        """
        raise ModelUnavailable("http_500")


@pytest.fixture
def traced(langsmith_stub, tracing_environ):
    """Enciende las trazas en el sustituto antes de armar el agente."""
    tracing.configure(load_settings(tracing_environ))
    return langsmith_stub


def _agent(model, knowledge_base, max_steps=4):
    return Agent(model, knowledge_base, max_steps=max_steps, max_question_chars=2000)


def _single_agent_run(stub):
    runs = stub.runs_named("agent_run")
    assert len(runs) == 1
    return runs[0]


@pytest.mark.parametrize(
    ("question", "max_steps", "outcome"),
    [
        (LAPTOP_PROBLEM, 4, "solved"),
        (PERSON_REQUEST, 4, "escalated"),
        (LAPTOP_PROBLEM, 1, "incomplete"),
    ],
    ids=["answer", "escalation", "step-cap"],
)
def test_every_way_out_of_the_loop_annotates_the_agent_run(
    traced, knowledge_base, question, max_steps, outcome
):
    agent = _agent(FakeModel(MODEL_NAME), knowledge_base, max_steps)
    result = agent.run(question, [], client="support")
    assert result.outcome == outcome
    run = _single_agent_run(traced)
    assert run.added_metadata == {
        "model": MODEL_NAME,
        "route": "default",
        "outcome": outcome,
        "escalated": result.escalated,
        "team": result.team,
        "article_id": result.article_id,
        "cached_calls": 0,
        "cost_usd": 0.0,
        "steps": result.steps,
        "client": "support",
    }
    expected_tags = {f"outcome:{outcome}", "route:default", f"model:{MODEL_NAME}"}
    assert set(run.tags) == expected_tags
    calls = traced.runs_named("model_complete")
    assert len(calls) == result.steps
    for call in calls:
        assert call.run_type == "llm"
        assert call.metadata == {"ls_provider": "fake", "ls_model_name": MODEL_NAME}


def test_run_takes_an_optional_client_by_keyword_and_works_without_it(
    traced, knowledge_base
):
    client = inspect.signature(Agent.run).parameters["client"]
    assert client.kind is inspect.Parameter.KEYWORD_ONLY
    assert client.default is None
    result = _agent(FakeModel(), knowledge_base).run(LAPTOP_PROBLEM, [])
    assert result.outcome == "solved"
    assert _single_agent_run(traced).added_metadata["client"] is None


def test_unavailable_model_is_not_annotated_and_the_error_still_reaches_the_caller(
    traced, knowledge_base
):
    agent = _agent(UnavailableModel(), knowledge_base)
    with pytest.raises(ModelUnavailable, match="http_500"):
        agent.run(LAPTOP_PROBLEM, [], client="support")
    run = _single_agent_run(traced)
    assert not run.added_metadata
    assert not run.tags


def test_each_model_names_its_provider_for_the_traces(gateway_stub):
    assert FakeModel().provider == "fake"
    assert FakeModel("fake-large").provider == "fake"
    stub = gateway_stub(gateway_stub.reply('{"answer": "Listo"}'))
    gateway = GatewayModel(
        name="@cf/meta/llama-3.1-8b-instruct-fast",
        account_id=stub.account,
        gateway_id=stub.gateway,
        api_token=stub.token,
        max_tokens=300,
        temperature=0,
        cache_ttl_seconds=0,
        http_client=stub.client(),
    )
    assert gateway.provider == "cloudflare"
