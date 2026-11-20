"""Pruebas unitarias de las reglas de compliance de producción.

Todas las claves y tokens son textos de ejemplo; ninguno es real.
"""

import pytest

from app.compliance import check_production
from app.config import ConfigError, load_settings

LONG_KEY = "example-production-key-0123"
# Exactamente 15 caracteres: uno menos que el mínimo de producción.
SHORT_KEY = "example-15-char"
TOKEN = "example-cloudflare-token"
VALID_PRODUCTION = {
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "example-account",
    "CF_GATEWAY_ID": "support-assistant",
    "CF_API_TOKEN": TOKEN,
    "API_KEYS": f"support:{LONG_KEY}",
}
BROKEN_RULES = {
    "fake-model": ({"MODEL_PROVIDER": "fake"}, "MODEL_PROVIDER"),
    "no-keys": ({"API_KEYS": ""}, "API_KEYS"),
    "short-key": ({"API_KEYS": f"support:{SHORT_KEY}"}, "API_KEYS"),
    "inputs-shown": (
        {"LANGSMITH_TRACING": "true", "HIDE_INPUTS": "false"},
        "HIDE_INPUTS",
    ),
    "outputs-shown": (
        {"LANGSMITH_TRACING": "true", "HIDE_OUTPUTS": "false"},
        "HIDE_OUTPUTS",
    ),
}


@pytest.mark.parametrize("rule", list(BROKEN_RULES))
def test_production_refuses_to_start_naming_the_broken_rule_without_secrets(rule):
    change, named = BROKEN_RULES[rule]
    with pytest.raises(ConfigError, match=named) as caught:
        load_settings({**VALID_PRODUCTION, **change})
    message = str(caught.value)
    for secret in (LONG_KEY, SHORT_KEY, TOKEN):
        assert secret not in message


def test_development_ignores_the_production_rules_and_valid_production_starts():
    for change, _named in BROKEN_RULES.values():
        environ = {**VALID_PRODUCTION, **change, "ENVIRONMENT": "development"}
        relaxed = load_settings(environ)
        assert relaxed.environment == "development"
        check_production(relaxed)
    production = load_settings(VALID_PRODUCTION)
    assert production.environment == "production"
    check_production(production)
