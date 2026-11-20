"""Pasos de los escenarios de ``features/ask.feature`` con pytest-bdd."""

from pytest_bdd import given, parsers, scenarios, then, when

STEP_CAP_MESSAGE = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
INVALID_QUESTIONS = {"empty": "", "blank": "   ", "too long": "a" * 2001}

scenarios("features/ask.feature")


@given("the support assistant is running", target_fixture="api")
def support_assistant_running(make_client):
    """El asistente con la configuración por omisión y el modelo simulado."""
    return make_client()


@given(
    parsers.parse("the support assistant is limited to {steps:d} step"),
    target_fixture="api",
)
def support_assistant_limited(make_client, steps):
    """El asistente con ``AGENT_MAX_STEPS`` reducido."""
    return make_client({"AGENT_MAX_STEPS": str(steps)})


@when(parsers.parse('an employee asks "{question}"'), target_fixture="response")
def employee_asks(api, question):
    """Manda la pregunta a ``POST /ask``."""
    return api.post("/ask", json={"question": question})


@when(
    parsers.parse("an employee sends a {kind} question"), target_fixture="response"
)
def employee_sends_invalid_question(api, kind):
    """Manda una pregunta vacía, en blanco o demasiado larga."""
    return api.post("/ask", json={"question": INVALID_QUESTIONS[kind]})


@then(parsers.parse('the answer contains "{text}"'))
def answer_contains(response, text):
    """La respuesta incluye el texto."""
    assert response.status_code == 200
    assert text in response.json()["answer"]


@then(parsers.parse('the answer does not contain "{text}"'))
def answer_does_not_contain(response, text):
    """La respuesta no incluye el texto."""
    assert response.status_code == 200
    assert text not in response.json()["answer"]


@then("the answer is the fixed step cap message")
def answer_is_step_cap_message(response):
    """La respuesta es exactamente el mensaje del tope."""
    assert response.json()["answer"] == STEP_CAP_MESSAGE


@then(parsers.parse('the tools used are "{tools}"'))
def tools_used_are(response, tools):
    """Las herramientas usadas, en orden, separadas por comas."""
    assert response.json()["tools_used"] == tools.split(", ")


@then("no tools are used")
def no_tools_used(response):
    """El agente respondió sin herramientas."""
    tools_used = response.json()["tools_used"]
    assert isinstance(tools_used, list)
    assert not tools_used


@then("the conversation is not escalated")
def not_escalated(response):
    """No hubo transferencia."""
    body = response.json()
    assert body["escalated"] is False
    assert body["team"] is None


@then(parsers.parse('the conversation is escalated to "{team}"'))
def escalated_to(response, team):
    """Hubo transferencia con el equipo y la respuesta lo nombra."""
    body = response.json()
    assert body["escalated"] is True
    assert body["team"] == team
    assert team in body["answer"]


@then(parsers.parse("the reported step count is {steps:d}"))
def reported_step_count(response, steps):
    """La cantidad de vueltas del bucle."""
    assert response.json()["steps"] == steps


@then("the request is rejected as invalid")
def rejected_as_invalid(response):
    """La API responde 422."""
    assert response.status_code == 422
