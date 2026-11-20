"""Pruebas unitarias del modo demo a través de la API (``PUBLIC_PAGE=true``)."""

import contextlib
import json
import sys
import types

import pytest

from app import tracing
from app.config import load_settings

API_KEY_HEADER = "X-API-Key"
FORWARDED_HEADER = "X-Forwarded-For"
VPN_PROBLEM = "No me puedo conectar a la VPN desde mi casa"
FORWARDED_ADDRESS = "198.51.100.42"
TINY_BUDGET = "0.000000001"
# Texto de ejemplo: nunca una clave real.
FAKE_LANGSMITH_KEY = "lsv2-example-key-for-tests"


@pytest.fixture
def trace_metadata(monkeypatch):
    """Instala un ``langsmith`` falso y devuelve los metadatos de cada traza.

    Al terminar, apaga las trazas para no afectar a otras pruebas.
    """
    recorded = []

    def tracing_context(**options):
        recorded.append(options.get("metadata"))
        return contextlib.nullcontext()

    def traceable(**_options):
        return lambda function: function

    module = types.ModuleType("langsmith")
    # Cliente falso: guarda sus opciones y nunca se conecta.
    module.Client = types.SimpleNamespace
    module.tracing_context = tracing_context
    module.traceable = traceable
    monkeypatch.setitem(sys.modules, "langsmith", module)
    yield recorded
    tracing.configure(load_settings({}))


def test_trace_metadata_names_the_public_client_and_never_the_ip(
    make_public_client, trace_metadata, public_peer
):
    observed = make_public_client(
        {
            "TRUST_PROXY": "true",
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": FAKE_LANGSMITH_KEY,
        }
    )
    response = observed.client.post(
        "/ask",
        json={"question": VPN_PROBLEM},
        headers={FORWARDED_HEADER: FORWARDED_ADDRESS},
    )
    assert response.status_code == 200
    assert len(trace_metadata) == 1
    assert trace_metadata[0]["client"] == "public"
    dumped = json.dumps(trace_metadata)
    assert FORWARDED_ADDRESS not in dumped
    assert public_peer not in dumped


def test_invalid_question_is_rejected_with_422_before_the_exhausted_budget(
    make_public_client, spy_model
):
    observed = make_public_client({"DAILY_BUDGET_USD": TINY_BUDGET}, model=spy_model)
    first = observed.client.post("/ask", json={"question": VPN_PROBLEM})
    assert first.status_code == 200
    calls = len(spy_model.calls)
    empty = observed.client.post("/ask", json={"question": "   "})
    assert empty.status_code == 422
    exhausted = observed.client.post("/ask", json={"question": VPN_PROBLEM})
    assert exhausted.status_code == 503
    assert len(spy_model.calls) == calls


def test_budget_rejection_counts_as_a_server_error_in_the_metrics(
    make_public_client, valid_api_key
):
    observed = make_public_client({"DAILY_BUDGET_USD": TINY_BUDGET})
    statuses = [
        observed.client.post("/ask", json={"question": VPN_PROBLEM}).status_code
        for _ in range(2)
    ]
    assert statuses == [200, 503]
    metrics = observed.client.get(
        "/metrics", headers={API_KEY_HEADER: valid_api_key}
    ).json()
    assert metrics["error_rate"] > 0
    assert metrics["public_cost_today_usd"] > metrics["daily_budget_usd"]
