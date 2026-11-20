"""Pasos de los escenarios de ``features/traces.feature`` con pytest-bdd.

Las trazas van al módulo ``langsmith`` sustituto de ``conftest.py``: nunca a la red.
"""

import sys

from pytest_bdd import given, parsers, scenarios, then, when

API_KEY_HEADER = "X-API-Key"
FORWARDED_HEADER = "X-Forwarded-For"
LAPTOP_PROBLEM = "Mi laptop no enciende"
VPN_PROBLEM = "No me puedo conectar a la VPN desde mi casa"
# Metadatos de agent_run que también están en el evento agent_run del log.
LOGGED_OUTCOME_FIELDS = (
    "model",
    "route",
    "outcome",
    "team",
    "article_id",
    "cached_calls",
    "cost_usd",
    "steps",
    "client",
)

scenarios("features/traces.feature")


def _single_agent_run(stub):
    """La única corrida ``agent_run`` registrada."""
    runs = stub.runs_named("agent_run")
    assert len(runs) == 1
    return runs[0]


def _model_calls(stub):
    """Las corridas ``model_complete``; debe haber al menos una."""
    runs = stub.runs_named("model_complete")
    assert runs, "no hubo trazas de llamadas al modelo"
    return runs


def _traced_assistant(make_observed_client, langsmith_stub, environ):
    """El asistente observado con las trazas encendidas en el sustituto."""
    observed = make_observed_client(environ)
    assert langsmith_stub.clients, "las trazas no se encendieron"
    return observed


@given("the traced support assistant is running", target_fixture="observed")
def traced_assistant_running(make_observed_client, langsmith_stub, tracing_environ):
    """Trazas encendidas, con ``HIDE_INPUTS`` y ``HIDE_OUTPUTS`` por omisión."""
    return _traced_assistant(make_observed_client, langsmith_stub, tracing_environ)


@given(
    parsers.parse(
        "the traced support assistant is running and LangSmith fails when {failure}"
    ),
    target_fixture="observed",
)
def traced_assistant_with_failing_langsmith(
    make_observed_client, langsmith_stub, tracing_environ, failure
):
    """Trazas encendidas con un sustituto que falla de la forma indicada."""
    langsmith_stub.failure = failure
    return _traced_assistant(make_observed_client, langsmith_stub, tracing_environ)


@given(
    "the traced demo assistant shows the conversation text behind a trusted proxy",
    target_fixture="public",
)
def traced_demo_assistant(make_public_client, langsmith_stub, tracing_environ):
    """Modo demo detrás de un proxy, con el texto visible para buscar fugas."""
    environ = {
        **tracing_environ,
        "TRUST_PROXY": "true",
        "HIDE_INPUTS": "false",
        "HIDE_OUTPUTS": "false",
    }
    public = make_public_client(environ)
    assert langsmith_stub.clients, "las trazas no se encendieron"
    return public


@given(
    "the support assistant asks for traces without a key and LangSmith cannot be "
    "loaded",
    target_fixture="observed",
)
def untraced_assistant(make_observed_client, monkeypatch):
    """``LANGSMITH_TRACING=true`` sin clave; importar ``langsmith`` fallaría."""
    monkeypatch.setitem(sys.modules, "langsmith", None)
    return make_observed_client({"LANGSMITH_TRACING": "true"})


@when(parsers.parse('an employee asks "{question}"'), target_fixture="response")
def employee_asks(observed, question):
    """Manda la pregunta a ``POST /ask`` con la clave de prueba."""
    return observed.client.post("/ask", json={"question": question})


@when(
    parsers.parse('a visitor asks through the proxy as "{address}"'),
    target_fixture="responses",
)
def visitor_asks_through_proxy(public, address):
    """Una pregunta sin clave reenviada por el proxy desde ``address``."""
    response = public.client.post(
        "/ask", json={"question": VPN_PROBLEM}, headers={FORWARDED_HEADER: address}
    )
    return [response]


@when(
    parsers.parse('the client with a key asks "{question}"'),
    target_fixture="responses",
)
def keyed_client_asks(public, responses, valid_api_key, question):
    """Una pregunta con ``X-API-Key`` válida en el modo demo."""
    response = public.client.post(
        "/ask", json={"question": question}, headers={API_KEY_HEADER: valid_api_key}
    )
    return [*responses, response]


@then(parsers.parse('the answer has status 200 and the outcome "{outcome}"'))
def answer_has_outcome(response, outcome):
    """La pregunta se respondió y terminó como se espera."""
    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


@then("the agent run trace has the ten outcome metadata of the answer")
def agent_run_has_outcome_metadata(observed, response, langsmith_stub):
    """Los diez metadatos de ``agent_run`` coinciden con la respuesta y el log."""
    body = response.json()
    logged = [
        event
        for event in observed.events(body["request_id"])
        if event["event"] == "agent_run"
    ]
    assert len(logged) == 1
    expected = {name: logged[0][name] for name in LOGGED_OUTCOME_FIELDS}
    expected["escalated"] = body["escalated"]
    assert _single_agent_run(langsmith_stub).added_metadata == expected


@then(
    parsers.parse(
        'the agent run trace is tagged with "{outcome_tag}", its route and its model'
    )
)
def agent_run_is_tagged(response, langsmith_stub, outcome_tag):
    """Las tres etiquetas para filtrar en LangSmith."""
    body = response.json()
    expected = {outcome_tag, f"route:{body['route']}", f"model:{body['model']}"}
    assert set(_single_agent_run(langsmith_stub).tags) == expected


@then(
    parsers.parse(
        'every model call is an llm trace from "{provider}" named after the '
        "answering model"
    )
)
def model_calls_are_llm_traces(response, langsmith_stub, provider):
    """Una traza ``llm`` por vuelta, con ``ls_provider`` y ``ls_model_name``."""
    body = response.json()
    calls = _model_calls(langsmith_stub)
    assert len(calls) == body["steps"]
    for run in calls:
        assert run.run_type == "llm"
        assert run.metadata["ls_provider"] == provider
        assert run.metadata["ls_model_name"] == body["model"]


@then("the token usage of the llm traces adds up to the tokens of the answer")
def usage_adds_up(response, langsmith_stub):
    """``usage_metadata`` de cada llamada suma los tokens de la respuesta."""
    body = response.json()
    usages = [run.outputs["usage_metadata"] for run in _model_calls(langsmith_stub)]
    assert sum(usage["input_tokens"] for usage in usages) == body["input_tokens"]
    assert sum(usage["output_tokens"] for usage in usages) == body["output_tokens"]
    for usage in usages:
        assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]


@then("no trace sends any input")
def no_input_is_sent(langsmith_stub):
    """Con ``HIDE_INPUTS=true`` ninguna corrida manda entradas."""
    assert langsmith_stub.runs
    for run in langsmith_stub.runs:
        assert not run.inputs, run.name


@then("the llm traces send only their usage metadata")
def llm_traces_send_only_usage(langsmith_stub):
    """Con ``HIDE_OUTPUTS=true`` de una llamada al modelo solo sale el consumo."""
    for run in _model_calls(langsmith_stub):
        assert set(run.outputs) == {"usage_metadata"}


@then("neither the question nor the answer is sent to LangSmith")
def conversation_is_not_sent(response, langsmith_stub):
    """El texto de la conversación no aparece en nada de lo que se manda."""
    sent = langsmith_stub.sent()
    assert LAPTOP_PROBLEM not in sent
    assert response.json()["answer"] not in sent


@then("both answers have status 200")
def both_answers_succeed(responses):
    """La pregunta pública y la pregunta con clave se respondieron."""
    assert [response.status_code for response in responses] == [200, 200]


@then(
    parsers.parse(
        'neither "{address}", the connection address nor any key is sent to LangSmith'
    )
)
def nothing_private_is_sent(
    langsmith_stub, address, public_peer, valid_api_key, tracing_environ
):
    """Ni IP ni clave, aunque el texto de la conversación sí sea visible."""
    sent = langsmith_stub.sent()
    assert VPN_PROBLEM in sent, "con HIDE_*=false el texto debe verse"
    private_values = (
        address,
        public_peer,
        valid_api_key,
        tracing_environ["LANGSMITH_API_KEY"],
    )
    for private in private_values:
        assert private not in sent


@then(parsers.parse('the agent run traces carry the clients "{first}" and "{second}"'))
def agent_runs_carry_clients(langsmith_stub, first, second):
    """Solo el nombre del cliente llega a los metadatos de ``agent_run``."""
    runs = langsmith_stub.runs_named("agent_run")
    assert [run.added_metadata.get("client") for run in runs] == [first, second]


@then("the log has no error event")
def log_has_no_error_event(observed):
    """La falla de LangSmith no llega al evento ``error`` del log."""
    names = [event["event"] for event in observed.events()]
    assert "agent_run" in names
    assert "error" not in names


@then(parsers.parse("the metrics report a latency target of {target:d} ms"))
def metrics_report_latency_target(observed, target):
    """``GET /metrics`` usa la meta de latencia por omisión."""
    response = observed.client.get("/metrics")
    assert response.status_code == 200
    assert response.json()["slo"]["p95_ms_target"] == target
