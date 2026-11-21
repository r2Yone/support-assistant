"""Pruebas de punta a punta de la página de la mesa de ayuda.

Cubren la sección «Pruebas de punta a punta» de ``spec/03-costs.md``,
``spec/04-production.md``, ``spec/05-demo.md`` y ``spec/07-page.md`` con el
producto corriendo con
el modelo simulado y en modo demo (``PUBLIC_PAGE=true``). La URL base la pone
la verificación; la página ya no pide clave.

Toda la suite hace como mucho 5 ``POST /ask``: la verificación arranca con el
límite por omisión de 5 preguntas por minuto por IP y todas las pruebas salen
de la misma dirección.
"""

import re

from playwright.sync_api import Page, expect

SOLVED_QUESTION = "No me puedo conectar a la VPN desde casa"
SOLVED_ARTICLE_ID = "KB-0001"
ESCALATED_QUESTION = "Mi teclado no funciona"
ESCALATED_TEAM = "Soporte en sitio"
SECOND_QUESTION = "Outlook no sincroniza el correo"
SECOND_ARTICLE_ID = "KB-0005"
SPANISH_EMPTY_ERROR = re.compile(r"pregunta.*vac[ií]a", re.IGNORECASE)
ASK_URL = re.compile(r"/ask$")
WELCOME_TEXT = (
    "Bienvenido al sitio de soporte con IA. Describe tu problema y buscaremos "
    "una solución, si no la encontramos, te transferimos con el equipo que "
    "puede ayudarte."
)
EXAMPLE_QUESTIONS = [
    "No me puedo conectar a la VPN desde mi casa",
    "Olvidé mi contraseña",
    "Mi teclado tiene teclas que no funcionan",
]


def ask(page: Page, question: str) -> dict:
    """Escribe una pregunta, la envía y devuelve el cuerpo de ``POST /ask``.

    También comprueba que la petición no lleva el encabezado ``X-API-Key``.

    :param page: Página de Playwright con la mesa de ayuda abierta
    :type page: Page
    :param question: Texto que escribe la persona
    :type question: str
    :return: Respuesta JSON de la API
    :rtype: dict
    """
    page.get_by_test_id("question").fill(question)
    with page.expect_response(ASK_URL) as response_info:
        page.get_by_test_id("send").click()
    response = response_info.value
    assert "x-api-key" not in response.request.headers, (
        "POST /ask mandó el encabezado X-API-Key"
    )
    assert response.ok, f"POST /ask respondió {response.status}"
    return response.json()


def test_solved_problem_shows_answer_with_request_id(page: Page):
    """Un problema con solución muestra la respuesta y su folio."""
    page.goto("/")
    body = ask(page, SOLVED_QUESTION)

    request_id = body["request_id"]
    assert request_id
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(SOLVED_ARTICLE_ID)
    expect(answer).to_contain_text(request_id)
    expect(page.get_by_test_id("escalation")).to_be_hidden()


def test_unsolved_problem_shows_escalation_with_team_and_folio(page: Page):
    """Un problema sin solución muestra el aviso de transferencia."""
    page.goto("/")
    body = ask(page, ESCALATED_QUESTION)

    assert body["escalated"] is True
    assert body["team"] == ESCALATED_TEAM
    escalation = page.get_by_test_id("escalation")
    expect(escalation).to_be_visible()
    expect(escalation).to_contain_text(ESCALATED_TEAM)
    expect(escalation).to_contain_text(body["request_id"])


def test_empty_question_shows_spanish_error(page: Page):
    """Una pregunta vacía (solo espacios) muestra un error en español."""
    page.goto("/")
    page.get_by_test_id("question").fill("   ")
    page.get_by_test_id("send").click()

    expect(page.get_by_test_id("answer")).to_contain_text(SPANISH_EMPTY_ERROR)
    expect(page.get_by_test_id("escalation")).to_be_hidden()


def test_second_question_keeps_previous_conversation(page: Page):
    """La segunda pregunta conserva en pantalla la conversación anterior."""
    page.goto("/")
    first = ask(page, SOLVED_QUESTION)
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(SOLVED_ARTICLE_ID)

    with page.expect_request(ASK_URL) as request_info:
        page.get_by_test_id("question").fill(SECOND_QUESTION)
        page.get_by_test_id("send").click()
    sent_request = request_info.value
    sent_history = sent_request.post_data_json["history"]

    expect(answer).to_contain_text(SECOND_ARTICLE_ID)
    expect(answer).to_contain_text(SOLVED_QUESTION)
    expect(answer).to_contain_text(SOLVED_ARTICLE_ID)
    expect(answer).to_contain_text(first["request_id"])
    expect(answer).to_contain_text(SECOND_QUESTION)
    assert "x-api-key" not in sent_request.headers
    assert sent_history == [
        {"role": "user", "content": SOLVED_QUESTION},
        {"role": "assistant", "content": first["answer"]},
    ]


def test_page_without_key_field_answers_a_question(page: Page):
    """La página no tiene campo de clave y responde una pregunta sin ella."""
    page.goto("/")
    expect(page.get_by_test_id("question")).to_be_visible()
    expect(page.get_by_test_id("api-key")).to_have_count(0)

    body = ask(page, SECOND_QUESTION)

    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(SECOND_ARTICLE_ID)
    expect(answer).to_contain_text(body["request_id"])
    assert page.evaluate("window.sessionStorage.length") == 0, (
        "La página guardó datos en sessionStorage"
    )


def test_opening_the_page_shows_the_welcome_text(page: Page):
    """Al abrir la página se ve el texto de bienvenida exacto."""
    page.goto("/")

    expect(page.get_by_text(WELCOME_TEXT, exact=True)).to_be_visible()


def test_clicking_an_example_writes_its_text_in_the_question(page: Page):
    """Pulsar cada ejemplo escribe su texto en el campo de pregunta.

    No envía nada: no gasta peticiones del límite por IP.
    """
    page.goto("/")
    examples = page.get_by_test_id("example")
    expect(examples).to_have_text(EXAMPLE_QUESTIONS)

    question = page.get_by_test_id("question")
    for text in EXAMPLE_QUESTIONS:
        examples.filter(has_text=text).click()
        expect(question).to_have_value(text)
