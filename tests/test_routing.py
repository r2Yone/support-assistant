"""Pruebas unitarias del enrutador por regla (palanca 1 de costo)."""

import pytest

from app.routing import Router

SMALL = "small-model"
LARGE = "large-model"
MAX_CHARS = 80
AT_THE_LIMIT = "a" * MAX_CHARS
OVER_THE_LIMIT = "a" * (MAX_CHARS + 1)


@pytest.mark.parametrize(
    ("enabled", "question", "model", "reason"),
    [
        (True, "Mi laptop no enciende", SMALL, "default"),
        (True, "¿Por qué se cae la VPN?", LARGE, "keyword:por qué"),
        (True, "POR QUE no imprime", LARGE, "keyword:por qué"),
        (True, "Explica cómo configuro el correo", LARGE, "keyword:explica"),
        (True, "Fallan VARIOS equipos", LARGE, "keyword:varios"),
        (True, "A todos nos falla el correo", LARGE, "keyword:todos"),
        (True, "Otra vez no me conecta la VPN", LARGE, "keyword:otra vez"),
        (True, "El monitor sigue sin imagen", LARGE, "keyword:sigue"),
        (True, "No imprime porque no hay papel", SMALL, "default"),
        (True, "Llegué de Todosantos sin internet", SMALL, "default"),
        (True, "Otra cosa: la vez pasada falló", SMALL, "default"),
        (True, AT_THE_LIMIT, SMALL, "default"),
        (True, OVER_THE_LIMIT, LARGE, "long_question"),
        (True, "Otra vez " + OVER_THE_LIMIT, LARGE, "long_question"),
        (False, "Mi laptop no enciende", LARGE, "routing_disabled"),
        (False, "Otra vez " + OVER_THE_LIMIT, LARGE, "routing_disabled"),
    ],
    ids=[
        "simple",
        "por-que",
        "por-que-capitals-no-accent",
        "explica",
        "varios",
        "todos",
        "otra-vez",
        "sigue",
        "porque-is-not-por-que",
        "todosantos-is-not-todos",
        "otra-and-vez-apart",
        "exactly-at-the-limit",
        "one-over-the-limit",
        "length-before-keyword",
        "disabled",
        "disabled-before-everything",
    ],
)
def test_router_picks_the_model_and_reason_for_each_question(
    enabled, question, model, reason
):
    router = Router(enabled=enabled, max_chars=MAX_CHARS, small=SMALL, large=LARGE)
    route = router.choose(question)
    assert (route.model, route.reason) == (model, reason)
