"""Pasos de los escenarios de ``features/production.feature`` con pytest-bdd."""

from datetime import timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

API_KEY_HEADER = "X-API-Key"
GATEWAY_AUTH_HEADER = "cf-aig-authorization"
WRONG_KEY = "wrong-key-sent-by-a-caller"
OTHER_CLIENT = "other-team"
# Texto de ejemplo: nunca una clave real.
OTHER_KEY = "example-other-key-9876543210"
VPN_PROBLEM = "No me puedo conectar a la VPN desde mi casa"
PUBLIC_PATHS = ("/", "/health", "/docs")

scenarios("features/production.feature")


@pytest.fixture
def answers():
    """Las respuestas de ``POST /ask`` del escenario, en orden."""
    return []


@pytest.fixture
def flaky_gateway(gateway_stub):
    """Un gateway simulado que responde una vez y después falla con ``500``."""
    return gateway_stub(
        gateway_stub.reply('{"answer": "Revisa la VPN (KB-0001)"}'),
        gateway_stub.failure(500),
    )


def _without_key(observed):
    """Quita la clave por omisión del cliente de prueba.

    :param observed: API observada del escenario.
    :return: El cliente de prueba, ya sin ``X-API-Key``.
    """
    observed.client.headers.pop(API_KEY_HEADER, None)
    return observed.client


def _events_named(observed, name):
    """Los eventos ``name`` del log, en orden."""
    return [event for event in observed.events() if event["event"] == name]


@given("the protected support assistant is running", target_fixture="observed")
def protected_assistant_running(make_observed_client):
    """El asistente con la clave de prueba y el log en memoria."""
    return make_observed_client()


@given(
    parsers.parse(
        "the protected support assistant allows {limit:d} questions per minute "
        "for two clients"
    ),
    target_fixture="observed",
)
def protected_assistant_with_limit(
    make_observed_client, valid_api_key, api_client_name, limit
):
    """El asistente con dos clientes y ``RATE_LIMIT_PER_MINUTE`` reducido."""
    keys = f"{api_client_name}:{valid_api_key},{OTHER_CLIENT}:{OTHER_KEY}"
    return make_observed_client(
        {"API_KEYS": keys, "RATE_LIMIT_PER_MINUTE": str(limit)}
    )


@given(
    "the protected support assistant uses a gateway that answers once and then fails",
    target_fixture="observed",
)
def protected_assistant_with_gateway(make_costed_client, gateway_stub, flaky_gateway):
    """El asistente con el modelo real y el gateway simulado."""
    return make_costed_client(
        gateway_stub.environ(), http_client=flaky_gateway.client()
    )


@when(
    parsers.parse("a caller sends {method} {path} {credential}"),
    target_fixture="response",
)
def caller_sends(observed, method, path, credential):
    """Manda la petición sin clave o con una clave equivocada."""
    client = _without_key(observed)
    headers = {API_KEY_HEADER: WRONG_KEY} if credential == "with a wrong key" else {}
    body = {"question": VPN_PROBLEM} if method == "POST" else None
    return client.request(method, path, json=body, headers=headers)


@when("a caller without a key sends an empty question", target_fixture="response")
def caller_sends_empty_question(observed):
    """Una petición sin clave y con un cuerpo que FastAPI rechazaría con 422."""
    return _without_key(observed).post("/ask", json={"question": ""})


@when(parsers.parse('the client asks "{question}"'), target_fixture="response")
def client_asks(observed, answers, question):
    """Manda la pregunta con la clave válida por omisión."""
    response = observed.client.post("/ask", json={"question": question})
    answers.append(response)
    return response


@when(parsers.parse("the client asks {count:d} questions"))
def client_asks_many(observed, answers, count):
    """Manda la misma pregunta varias veces con la clave válida."""
    for _ in range(count):
        answers.append(observed.client.post("/ask", json={"question": VPN_PROBLEM}))


@then(
    parsers.parse(
        'the response is 401 "{detail}" with the generated request id'
    )
)
def response_is_unauthorized(response, detail, generated_id):
    """Un ``401`` con el folio en el cuerpo y en el encabezado."""
    assert response.status_code == 401
    assert response.json() == {"detail": detail, "request_id": generated_id}
    assert response.headers["X-Request-ID"] == generated_id


@then("the log has a request event with status 401 and no client")
def request_event_without_client(observed):
    """El middleware de observabilidad queda por fuera y registra el ``401``."""
    requests = _events_named(observed, "request")
    assert [event["status"] for event in requests] == [401]
    assert requests[0]["client"] is None


@then(parsers.parse('the key "{key}" appears nowhere in the log'))
def key_not_in_log(observed, key):
    """La clave enviada no se escribe en el log."""
    assert key not in observed.log.getvalue()


@then('"/", "/health" and "/docs" answer 200 without a key')
def public_paths_answer(observed):
    """La página, la salud y la documentación no piden clave."""
    client = _without_key(observed)
    for path in PUBLIC_PATHS:
        assert client.get(path).status_code == 200, path


@then(parsers.parse('the answer has status 200 and the outcome "{outcome}"'))
def answer_has_outcome(response, outcome):
    """La respuesta es la misma de antes de exigir clave."""
    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


@then("the request, agent run and audit events carry the client name")
def events_carry_client(observed, response, api_client_name):
    """Cada evento del folio lleva el nombre del cliente."""
    events = observed.events(response.json()["request_id"])
    for name in ("request", "agent_run", "audit"):
        named = [event for event in events if event["event"] == name]
        assert named, name
        assert all(event["client"] == api_client_name for event in named), name


@then("the valid key appears nowhere in the log")
def valid_key_not_in_log(observed, valid_api_key):
    """La clave válida no se escribe en el log."""
    assert valid_api_key not in observed.log.getvalue()


@then(
    parsers.parse(
        'the last response is 429 "{detail}" with a Retry-After of at least 1'
    )
)
def last_response_is_rate_limited(answers, detail, generated_id):
    """Las primeras pasan; la que excede el límite da ``429`` con ``Retry-After``."""
    statuses = [response.status_code for response in answers]
    assert statuses == [200] * (len(answers) - 1) + [429]
    limited = answers[-1]
    assert limited.json() == {"detail": detail, "request_id": generated_id}
    assert 1 <= int(limited.headers["Retry-After"]) <= 60


@then("the other client can still ask")
def other_client_can_ask(observed):
    """El límite es por cliente."""
    response = observed.client.post(
        "/ask", json={"question": VPN_PROBLEM}, headers={API_KEY_HEADER: OTHER_KEY}
    )
    assert response.status_code == 200


@then("after 60 seconds the client can ask again")
def client_can_ask_after_window(observed):
    """Al pasar la ventana de 60 s del reloj inyectado, el cliente vuelve a entrar."""
    observed.clock.current += timedelta(seconds=60)
    response = observed.client.post("/ask", json={"question": VPN_PROBLEM})
    assert response.status_code == 200


@then("every gateway request carries the token in the authenticated gateway header")
def gateway_requests_are_authenticated(flaky_gateway):
    """Cada petición al gateway lleva ``cf-aig-authorization`` con el token."""
    assert len(flaky_gateway.requests) == 2
    for request in flaky_gateway.requests:
        expected = f"Bearer {flaky_gateway.token}"
        assert request.headers[GATEWAY_AUTH_HEADER] == expected


@then("the second response is 502 without the token")
def second_response_is_bad_gateway(answers, flaky_gateway):
    """Un fallo del gateway no devuelve el token a la persona."""
    assert answers[0].status_code == 200
    failed = answers[1]
    assert failed.status_code == 502
    assert flaky_gateway.token not in failed.text
    assert flaky_gateway.token not in str(failed.headers)


@then("the token appears nowhere in the log")
def token_not_in_log(observed, flaky_gateway):
    """Ni el token ni el encabezado del gateway llegan al log."""
    log = observed.log.getvalue()
    assert flaky_gateway.token not in log
    assert GATEWAY_AUTH_HEADER not in log
