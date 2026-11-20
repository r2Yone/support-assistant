"""Pasos de los escenarios de ``features/demo.feature`` con pytest-bdd.

El modo demo se arma con ``make_public_client``: el cliente no manda clave y se
conecta desde una IP de documentación. Las direcciones son de ejemplo (RFC 5737).
"""

from datetime import timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

API_KEY_HEADER = "X-API-Key"
FORWARDED_HEADER = "X-Forwarded-For"
PUBLIC_CLIENT = "public"
VPN_PROBLEM = "No me puedo conectar a la VPN desde mi casa"
OTHER_PEER = "203.0.113.99"
FORGED_FIRST_ENTRY = "192.0.2.77"
TINY_BUDGET = "0.000000001"
REJECTED_STEP = 'the response is 401 "{detail}" with the generated request id'
LIMITED_STEP = 'the last response is 429 "{detail}" with a Retry-After of at least 1'

scenarios("features/demo.feature")


@pytest.fixture
def call_counts():
    """Llamadas acumuladas al modelo espía después de cada pregunta."""
    return []


@pytest.fixture
def answers():
    """Las respuestas de ``POST /ask`` del escenario, en orden."""
    return []


def _ask(client, headers=None):
    """Manda la pregunta de la VPN con los encabezados dados."""
    return client.post("/ask", json={"question": VPN_PROBLEM}, headers=headers)


def _named(observed, name):
    """Los eventos ``name`` del log, en orden."""
    return [event for event in observed.events() if event["event"] == name]


def _public_metrics(observed, valid_api_key):
    """``GET /metrics`` con la clave válida."""
    headers = {API_KEY_HEADER: valid_api_key}
    response = observed.client.get("/metrics", headers=headers)
    assert response.status_code == 200
    return response.json()


@given("the demo support assistant is running", target_fixture="observed")
def demo_assistant_running(make_public_client):
    """El modo demo con los valores por omisión."""
    return make_public_client()


@given(
    parsers.parse(
        "the demo support assistant allows {limit:d} question per minute "
        "and a tiny budget"
    ),
    target_fixture="observed",
)
def demo_assistant_with_tiny_limits(make_public_client, limit):
    """El modo demo con un límite por IP y un tope diminutos."""
    environ = {
        "PUBLIC_RATE_LIMIT_PER_MINUTE": str(limit),
        "DAILY_BUDGET_USD": TINY_BUDGET,
    }
    return make_public_client(environ)


@given(
    parsers.re(
        r"the demo support assistant (?P<proxy>behind a trusted proxy )?allows "
        r"(?P<limit>\d+) public questions? per minute"
    ),
    target_fixture="observed",
)
def demo_assistant_with_ip_limit(make_public_client, proxy, limit):
    """El modo demo con ``PUBLIC_RATE_LIMIT_PER_MINUTE`` y, si se pide, el proxy."""
    environ = {"PUBLIC_RATE_LIMIT_PER_MINUTE": limit}
    if proxy:
        environ["TRUST_PROXY"] = "true"
    return make_public_client(environ)


@given(
    "the demo support assistant has a tiny daily budget and a spy model",
    target_fixture="observed",
)
def demo_assistant_with_tiny_budget(make_public_client, spy_model):
    """El modo demo con un tope que la primera respuesta ya agota."""
    return make_public_client({"DAILY_BUDGET_USD": TINY_BUDGET}, model=spy_model)


@when(parsers.parse('a visitor asks "{question}"'), target_fixture="response")
def visitor_asks(observed, answers, question):
    """Una pregunta sin clave."""
    response = observed.client.post("/ask", json={"question": question})
    answers.append(response)
    return response


@when(
    parsers.re(r'a caller asks with the key "(?P<key>[^"]*)"'),
    target_fixture="response",
)
def caller_asks_with_key(observed, key):
    """Una pregunta con ``X-API-Key`` presente: equivocada o vacía."""
    return _ask(observed.client, {API_KEY_HEADER: key})


@when(parsers.parse("the client with a key asks {count:d} questions"))
def keyed_client_asks(observed, answers, valid_api_key, count):
    """Preguntas con la clave válida."""
    for _ in range(count):
        answers.append(_ask(observed.client, {API_KEY_HEADER: valid_api_key}))


@when(parsers.parse("the visitor asks {count:d} questions"))
def visitor_asks_many(observed, answers, call_counts, spy_model, count):
    """Preguntas sin clave desde la misma IP; guarda las llamadas al modelo."""
    for _ in range(count):
        answers.append(_ask(observed.client))
        call_counts.append(len(spy_model.calls))


@when(
    parsers.re(
        r'the visitor asks through the proxy as "(?P<address>[\d.]+)"'
    )
)
def visitor_asks_through_proxy(observed, answers, address):
    """Una pregunta sin clave con la dirección que agrega el proxy."""
    answers.append(_ask(observed.client, {FORWARDED_HEADER: address}))


@when("the visitor asks again through the proxy with a forged first entry")
def visitor_forges_first_entry(observed, answers):
    """Repite la última dirección, con otra primera entrada escrita a mano."""
    last = answers[-1].request.headers[FORWARDED_HEADER]
    forged = f"{FORGED_FIRST_ENTRY}, {last}"
    answers.append(_ask(observed.client, {FORWARDED_HEADER: forged}))


@then(parsers.parse('the answer has status 200 and the outcome "{outcome}"'))
def answer_is_solved(response, outcome):
    """La pregunta pública responde igual que con clave."""
    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


@then('the request, agent run and audit events carry the client "public"')
def events_carry_public_client(observed):
    """Los eventos de la petición pública se atribuyen a ``public``."""
    for name in ("request", "agent_run", "audit"):
        named = _named(observed, name)
        assert named, name
        assert {event["client"] for event in named} == {PUBLIC_CLIENT}, name


@then(parsers.parse(REJECTED_STEP))
def response_is_rejected(response, detail, generated_id):
    """Una clave presente e inválida nunca baja a ``public``."""
    assert (response.status_code, response.json()) == (
        401,
        {"detail": detail, "request_id": generated_id},
    )


@then("every keyed answer has status 200 and carries the client name")
def keyed_answers_pass(observed, answers, api_client_name):
    """Ni el límite por IP ni el tope tocan al cliente con clave."""
    assert [response.status_code for response in answers] == [200, 200, 200]
    clients = [event["client"] for event in _named(observed, "request")]
    assert clients == [PUBLIC_CLIENT, api_client_name, api_client_name]


@then("the visitor is still the only one counted in the public spending")
def only_visitor_is_counted(observed, answers, valid_api_key):
    """Lo que gastan las peticiones con clave no suma al tope de la demo."""
    metrics = _public_metrics(observed, valid_api_key)
    visitor_cost = answers[0].json()["cost_usd"]
    assert metrics["public_cost_today_usd"] == pytest.approx(visitor_cost)


@then("GET /metrics without a key answers 401")
def metrics_need_a_key(observed):
    """``/metrics`` nunca es público."""
    assert observed.client.get("/metrics").status_code == 401


@then(
    parsers.parse(
        "GET /metrics with a key reports the public cost of the visitor "
        "and a budget of {budget:g}"
    )
)
def metrics_report_budget(observed, response, valid_api_key, budget):
    """``/metrics`` agrega el gasto público de hoy y el tope."""
    metrics = _public_metrics(observed, valid_api_key)
    assert response.json()["cost_usd"] > 0
    expected = response.json()["cost_usd"]
    assert metrics["public_cost_today_usd"] == pytest.approx(expected)
    assert metrics["daily_budget_usd"] == pytest.approx(budget)


@then(parsers.parse(LIMITED_STEP))
def last_public_response_is_limited(answers, detail, generated_id):
    """El límite por IP responde igual que el límite por cliente."""
    statuses = [response.status_code for response in answers]
    assert statuses[-1] == 429
    assert set(statuses[:-1]) == {200}
    limited = answers[-1]
    assert limited.json() == {"detail": detail, "request_id": generated_id}
    assert 1 <= int(limited.headers["Retry-After"]) <= 60


@then("a visitor from another IP can still ask")
def other_ip_can_ask(observed):
    """El límite es por dirección IP."""
    assert _ask(observed.client_from(OTHER_PEER)).status_code == 200


@then("after 60 seconds the visitor can ask again")
def visitor_can_ask_after_window(observed):
    """La ventana de 60 s usa el reloj inyectado."""
    observed.clock.current += timedelta(seconds=60)
    assert _ask(observed.client).status_code == 200


@then("the second response is 429")
def second_response_is_limited(answers):
    """La segunda pregunta cuenta para la misma IP que la primera."""
    assert [response.status_code for response in answers] == [200, 429]


@then(parsers.parse('a visitor forwarded as "{address}" can still ask'))
def forwarded_visitor_can_ask(observed, address):
    """Con el proxy de confianza, la última entrada distingue a las personas."""
    response = _ask(observed.client, {FORWARDED_HEADER: address})
    assert response.status_code == 200


@then(
    parsers.parse(
        'neither "{address}" nor the connection address appear in the log'
    )
)
def ip_not_in_log(observed, answers, public_peer, address):
    """La IP es un dato personal: nunca se escribe."""
    assert answers[0].status_code == 200
    log = observed.log.getvalue()
    assert address not in log
    assert public_peer not in log


@then(
    parsers.parse(
        'the first answer costs money and the next two are 503 "{detail}"'
    )
)
def budget_rejects_after_first(answers, detail, generated_id):
    """Antes de llamar al modelo, el tope agotado da ``503``."""
    first, *rejected = answers
    assert first.status_code == 200
    assert first.json()["cost_usd"] > 0
    for response in rejected:
        assert response.status_code == 503
        assert response.json() == {"detail": detail, "request_id": generated_id}


@then("the model was called only for the first question")
def model_called_once(call_counts):
    """Un ``503`` por el tope nunca llama al modelo."""
    assert call_counts[0] > 0
    assert call_counts == [call_counts[0]] * 3


@then("the log has the request statuses 200, 503 and 503")
def request_statuses_logged(observed):
    """El evento ``request`` registra cada ``503``."""
    statuses = [event["status"] for event in _named(observed, "request")]
    assert statuses == [200, 503, 503]


@then("the log has one budget_exhausted event with the spent amount and the budget")
def one_budget_event(observed, answers):
    """El aviso se escribe una sola vez por día, con lo gastado y el tope."""
    events = _named(observed, "budget_exhausted")
    assert len(events) == 1
    spent = answers[0].json()["cost_usd"]
    assert events[0]["spent_usd"] == pytest.approx(spent)
    assert events[0]["budget_usd"] == pytest.approx(float(TINY_BUDGET))


@then("the client with a key can still ask")
def keyed_client_ignores_budget(observed, valid_api_key):
    """El tope es solo de la demo."""
    response = _ask(observed.client, {API_KEY_HEADER: valid_api_key})
    assert response.status_code == 200


@then("on the next UTC day the visitor can ask again")
def visitor_asks_next_day(observed):
    """Al cambiar el día UTC del reloj inyectado, la suma vuelve a cero."""
    observed.clock.current += timedelta(days=1)
    assert _ask(observed.client).status_code == 200
