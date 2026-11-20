"""Pasos de los escenarios de ``features/costs.feature`` con pytest-bdd."""

import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

MODELS = {
    "small": "@cf/meta/llama-3.1-8b-instruct-fast",
    "large": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
}

scenarios("features/costs.feature")


@pytest.fixture
def answers():
    """Las respuestas de ``POST /ask`` del escenario, en orden."""
    return []


@pytest.fixture
def sent_history():
    """El historial que mandó la persona en el escenario."""
    return []


def _metrics(observed):
    """Lo que devuelve ``GET /metrics``."""
    response = observed.client.get("/metrics")
    assert response.status_code == 200
    return response.json()


@given("the costed support assistant is running", target_fixture="observed")
def costed_assistant_running(make_costed_client):
    """El asistente con sus modelos simulados con nombre y la tabla de precios."""
    return make_costed_client()


@given(
    parsers.parse('the costed support assistant is running with routing "{routing}"'),
    target_fixture="observed",
)
def costed_assistant_with_routing(make_costed_client, routing):
    """El asistente con ``ROUTING`` encendido o apagado."""
    return make_costed_client({"ROUTING": routing})


@given(
    "the costed support assistant is running with a model that records its messages",
    target_fixture="observed",
)
def costed_assistant_with_spy(make_costed_client, spy_model):
    """El asistente con un modelo simulado que guarda los mensajes que recibe."""
    return make_costed_client(model=spy_model)


@given(
    "the costed support assistant uses a gateway that fails",
    target_fixture="observed",
)
def costed_assistant_with_failing_gateway(make_costed_client, gateway_stub):
    """El asistente con el modelo real y un gateway que responde 500."""
    stub = gateway_stub(gateway_stub.failure(500))
    return make_costed_client(gateway_stub.environ(), http_client=stub.client())


@when(parsers.parse('an employee asks "{question}"'), target_fixture="response")
def employee_asks(observed, answers, question):
    """Manda la pregunta a ``POST /ask`` y guarda la respuesta."""
    response = observed.client.post("/ask", json={"question": question})
    answers.append(response)
    return response


@when(
    parsers.parse(
        'an employee with {count:d} previous messages asks "{question}"'
    ),
    target_fixture="response",
)
def employee_asks_with_history(observed, sent_history, count, question):
    """Manda la pregunta con un historial que alterna persona y asistente."""
    sent_history.extend(
        {
            "role": "user" if number % 2 else "assistant",
            "content": f"Mensaje previo número {number}",
        }
        for number in range(1, count + 1)
    )
    return observed.client.post(
        "/ask", json={"question": question, "history": sent_history}
    )


@then(parsers.parse('the answer used the {size} model with route "{route}"'))
def answer_used_model(response, size, route):
    """El modelo y el motivo del enrutador que reporta la respuesta."""
    assert response.status_code == 200
    body = response.json()
    assert (body["model"], body["route"]) == (MODELS[size], route)


@then("the answer cost more than 0 without cached calls")
def answer_cost_above_zero(response):
    """El modelo simulado se cobra con el precio de su nombre."""
    body = response.json()
    assert body["cost_usd"] > 0
    assert body["cached_calls"] == 0


@then("the agent run logs the model, route, cached calls and cost of the answer")
def agent_run_logs_cost(observed, response):
    """El evento ``agent_run`` lleva los cuatro campos de la respuesta."""
    body = response.json()
    runs = [
        event
        for event in observed.events(body["request_id"])
        if event["event"] == "agent_run"
    ]
    assert len(runs) == 1
    for field in ("model", "route", "cached_calls", "cost_usd"):
        assert runs[0][field] == body[field]


@then("the second answer cost more than the first")
def second_answer_costs_more(answers):
    """El modelo grande cuesta más que el chico por el mismo problema."""
    cheap, expensive = (response.json() for response in answers)
    assert cheap["model"] == MODELS["small"]
    assert expensive["model"] == MODELS["large"]
    assert expensive["cost_usd"] > cheap["cost_usd"] > 0


@then(
    parsers.parse(
        "the model received only the last {kept:d} previous messages and the question"
    )
)
def model_received_window(response, spy_model, sent_history, kept):
    """La primera llamada al modelo lleva la ventana del historial y la pregunta."""
    assert response.status_code == 200
    question = {"role": "user", "content": "Mi laptop no enciende"}
    assert spy_model.calls[0] == sent_history[-kept:] + [question]


@then(parsers.parse('the answer contains "{text}"'))
def answer_contains(response, text):
    """La respuesta incluye el texto."""
    assert response.status_code == 200
    assert text in response.json()["answer"]


@then(parsers.parse('the answer is exactly "{text}"'))
def answer_is_exactly(response, text):
    """La respuesta es exactamente el texto."""
    assert response.status_code == 200
    assert response.json()["answer"] == text


@then("the conversation is not escalated")
def not_escalated(response):
    """No hubo transferencia."""
    body = response.json()
    assert body["escalated"] is False
    assert body["team"] is None


@then(parsers.parse("the reported step count is {steps:d}"))
def reported_step_count(response, steps):
    """La cantidad de vueltas del bucle."""
    assert response.json()["steps"] == steps


@then(parsers.parse('the outcome is "{outcome}"'))
def outcome_is(response, outcome):
    """La respuesta dice cómo terminó la pregunta."""
    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


@then("the metrics report a cost above 0 and a cost per solved problem up to it")
def metrics_cost_per_solved(observed):
    """El costo por problema resuelto está entre 0 y el costo acumulado."""
    metrics = _metrics(observed)
    assert metrics["cost_usd"] > 0
    assert 0 < metrics["cost_per_solved_usd"] <= metrics["cost_usd"]


@then("the metrics report a cost above 0 and a cost per solved problem of 0")
def metrics_cost_without_solved(observed):
    """Sin preguntas resueltas, el costo por problema resuelto es 0."""
    metrics = _metrics(observed)
    assert metrics["cost_usd"] > 0
    assert metrics["cost_per_solved_usd"] == 0


@then(
    parsers.parse('the response is "{detail}" with the generated request id')
)
def response_is_bad_gateway(response, detail, generated_id):
    """Un ``502`` que da el folio a la persona."""
    assert response.status_code == 502
    assert response.json() == {"detail": detail, "request_id": generated_id}
    assert response.headers["X-Request-ID"] == generated_id


@then("the log has one error event with its type and no gateway secret")
def error_event_without_secrets(observed, gateway_stub):
    """El evento ``error`` lleva el tipo; ningún evento lleva cuenta, token o cuerpo."""
    errors = [event for event in observed.events() if event["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["error_type"]
    secrets = (gateway_stub.account, gateway_stub.token, gateway_stub.secret_body)
    for event in observed.events():
        dumped = json.dumps(event, ensure_ascii=False)
        assert all(secret not in dumped for secret in secrets)


@then("the metrics report an error rate above 0")
def error_rate_above_zero(observed):
    """El ``502`` cuenta en la tasa de error."""
    assert _metrics(observed)["error_rate"] > 0
