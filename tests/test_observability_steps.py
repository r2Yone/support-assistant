"""Pasos de los escenarios de ``features/observability.feature`` con pytest-bdd."""

import json

from pytest_bdd import given, parsers, scenarios, then, when

LAPTOP_PROBLEM = "Mi laptop no enciende"
UNSAFE_REQUEST_IDS = {"too long": "a" * 200, "with a slash": "folio/123"}

scenarios("features/observability.feature")


def _events_of(observed, response, name):
    """Los eventos ``name`` del folio de la respuesta."""
    request_id = response.headers["X-Request-ID"]
    return [event for event in observed.events(request_id) if event["event"] == name]


def _agent_run(observed, response):
    """El único evento ``agent_run`` del folio de la respuesta."""
    runs = _events_of(observed, response, "agent_run")
    assert len(runs) == 1
    return runs[0]


def _metrics(observed):
    """Lo que devuelve ``GET /metrics``."""
    response = observed.client.get("/metrics")
    assert response.status_code == 200
    return response.json()


@given("the observed support assistant is running", target_fixture="observed")
def observed_assistant_running(make_observed_client):
    """El asistente con la configuración por omisión y el log en memoria."""
    return make_observed_client()


@given(
    parsers.parse(
        'the observed support assistant is running with "{name}" set to "{value}"'
    ),
    target_fixture="observed",
)
def observed_assistant_with_variable(make_observed_client, name, value):
    """El asistente con una variable de entorno cambiada."""
    return make_observed_client({name: value})


@given(
    parsers.parse("the observed support assistant is limited to {steps:d} step"),
    target_fixture="observed",
)
def observed_assistant_limited(make_observed_client, steps):
    """El asistente con ``AGENT_MAX_STEPS`` reducido."""
    return make_observed_client({"AGENT_MAX_STEPS": str(steps)})


@given(
    "the observed support assistant runs with a model that fails",
    target_fixture="observed",
)
def observed_assistant_failing(make_observed_client, failing_model):
    """El asistente con un modelo que lanza una excepción."""
    return make_observed_client(model=failing_model)


@when(parsers.parse('an employee asks "{question}"'), target_fixture="response")
def employee_asks(observed, question):
    """Manda la pregunta a ``POST /ask`` sin ``X-Request-ID``."""
    return observed.client.post("/ask", json={"question": question})


@when(
    parsers.parse('an employee with the request id "{request_id}" asks "{question}"'),
    target_fixture="response",
)
def employee_asks_with_request_id(observed, request_id, question):
    """Manda la pregunta con el encabezado ``X-Request-ID``."""
    return observed.client.post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )


@when(
    parsers.parse("an employee sends a request id that is {kind}"),
    target_fixture="response",
)
def employee_sends_unsafe_request_id(observed, kind):
    """Manda una pregunta con un ``X-Request-ID`` inseguro."""
    headers = {"X-Request-ID": UNSAFE_REQUEST_IDS[kind]}
    return observed.client.post(
        "/ask", json={"question": LAPTOP_PROBLEM}, headers=headers
    )


@then(parsers.parse('the outcome is "{outcome}"'))
def outcome_is(response, outcome):
    """La respuesta dice cómo terminó la pregunta."""
    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


@then(parsers.parse('the logged article is "{article}"'))
def logged_article_is(observed, response, article):
    """El ``article_id`` de ``agent_run``; ``none`` significa ``null``."""
    expected = None if article == "none" else article
    assert _agent_run(observed, response)["article_id"] == expected


@then("the agent run is logged as stopped")
def agent_run_stopped(observed, response):
    """El agente llegó al tope de vueltas."""
    event = _agent_run(observed, response)
    assert event["stopped"] is True
    assert event["steps"] == 1
    assert event["outcome"] == "incomplete"


@then(parsers.parse('the request id in the header and in the body is "{request_id}"'))
def request_id_is(response, request_id):
    """El folio va en el encabezado y en el cuerpo."""
    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["request_id"] == request_id


@then("the request id in the header and in the body is the generated one")
def request_id_is_generated(response, generated_id):
    """El folio inseguro se reemplazó por el que genera el ``id_factory``."""
    assert response.headers["X-Request-ID"] == generated_id
    assert response.json()["request_id"] == generated_id


@then(parsers.parse('the log events of "{request_id}" are "{names}" in that order'))
def log_events_in_order(observed, request_id, names):
    """Los eventos del folio, en orden, con los campos comunes."""
    events = observed.events(request_id)
    assert [event["event"] for event in events] == names.split(", ")
    for event in events:
        assert event["service"] == "support-assistant"
        assert event["ts"]


@then(
    parsers.parse(
        'the audit shows the search found "{article_id}" in category "{category}"'
    )
)
def audit_shows_search(observed, response, article_id, category):
    """El ``audit`` de la búsqueda trae categoría e ids, no el texto."""
    audits = _events_of(observed, response, "audit")
    assert len(audits) == 1
    audit = audits[0]
    assert audit["action"] == "tool_call"
    assert audit["tool"] == "search_knowledge_base"
    assert audit["category"] == category
    assert article_id in audit["article_ids"]
    assert audit["problem_chars"] > 0
    assert "problem" not in audit


@then(
    parsers.parse(
        'the request event shows "{method} {path}" with status {status:d} '
        "and its latency"
    )
)
def request_event_shows(observed, response, method, path, status):
    """El evento ``request`` trae método, ruta, código y latencia."""
    requests = _events_of(observed, response, "request")
    assert len(requests) == 1
    event = requests[0]
    assert (event["method"], event["path"], event["status"]) == (method, path, status)
    assert event["latency_ms"] >= 0


@then("the agent run has no question and no answer")
def agent_run_without_text(observed, response):
    """Con ``LOG_CONVERSATION_TEXT=false`` no hay texto de la conversación."""
    event = _agent_run(observed, response)
    assert "question" not in event
    assert "answer" not in event
    assert event["article_id"] == "KB-0001"


@then(parsers.parse('the question "{question}" appears nowhere in the log'))
def question_nowhere_in_log(observed, question):
    """Ninguna línea del log contiene la pregunta."""
    for event in observed.events():
        assert question not in json.dumps(event, ensure_ascii=False)


@then("the response is an internal error with the generated request id")
def internal_error_with_request_id(response, generated_id):
    """Un ``500`` genérico que da el folio a la persona."""
    assert response.status_code == 500
    assert response.json() == {"detail": "internal error", "request_id": generated_id}
    assert response.headers["X-Request-ID"] == generated_id


@then(
    parsers.parse(
        'the log has an error event of type "{error_type}" without its message'
    )
)
def error_event_logged(observed, failing_model, error_type):
    """El evento ``error`` lleva el tipo y nunca el mensaje de la excepción."""
    errors = [event for event in observed.events() if event["event"] == "error"]
    assert len(errors) == 1
    assert error_type in errors[0].values()
    for event in observed.events():
        assert failing_model.message not in json.dumps(event, ensure_ascii=False)


@then("the metrics report an error rate above 0")
def error_rate_above_zero(observed):
    """El ``500`` cuenta en la tasa de error."""
    assert _metrics(observed)["error_rate"] > 0


@then(parsers.parse('the metrics count the outcomes "{counts}"'))
def metrics_count_outcomes(observed, counts):
    """Cuántas preguntas terminaron de cada forma."""
    expected = {}
    for pair in counts.split(", "):
        name, value = pair.split("=")
        expected[name] = int(value)
    assert _metrics(observed)["outcomes"] == expected


@then(parsers.parse("the self service rate is {rate:f}"))
def self_service_rate_is(observed, rate):
    """Preguntas resueltas sin humano entre preguntas respondidas."""
    assert _metrics(observed)["self_service_rate"] == rate


@then("the metrics report the tokens used")
def metrics_report_tokens(observed):
    """Los tokens del modelo se acumulan."""
    tokens = _metrics(observed)["tokens"]
    assert tokens["input"] > 0
    assert tokens["output"] > 0
