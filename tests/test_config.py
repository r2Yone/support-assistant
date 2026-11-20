"""Pruebas unitarias de la configuración por variables de entorno."""

import os
import re
from pathlib import Path

import pytest

from app.config import DEFAULTS, ConfigError, load_settings

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = "account-0123456789"
TOKEN = "token-secret-abcdef"
# Texto de ejemplo: nunca una clave real.
API_KEY = "example-config-key-0123456"
ASSIGNMENT = re.compile(r"([A-Z][A-Z0-9_]*)=(.*)")
SECRET_VARIABLES = ("API_KEYS", "CF_ACCOUNT_ID", "CF_API_TOKEN", "LANGSMITH_API_KEY")


def _env_example():
    """Lee ``.env.example``: variables activas y variables comentadas."""
    active, commented = {}, {}
    text = (PRODUCT_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        target = commented if stripped.startswith("#") else active
        found = ASSIGNMENT.fullmatch(stripped.lstrip("#").strip())
        if found:
            target[found.group(1)] = found.group(2).strip()
    return active, commented


@pytest.fixture
def restore_environ():
    """Devuelve ``os.environ`` a como estaba: ``python-dotenv`` lo modifica."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def write_product_file():
    """Escribe archivos en la raíz de ``product/`` y los borra al terminar."""
    written = []

    def _write(name, content):
        path = PRODUCT_ROOT / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
        return path

    yield _write
    for path in written:
        path.unlink(missing_ok=True)


def test_defaults_are_used_when_the_environment_is_empty():
    settings = load_settings({})
    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 4
    assert settings.max_question_chars == 2000
    assert settings.kb_min_score == 2
    assert settings.kb_max_results == 2
    kb_path = Path(settings.kb_path)
    assert kb_path.is_file()
    assert kb_path.parts[-2:] == ("data", "knowledge_base.json")
    assert load_settings({"AGENT_MAX_STEPS": "6"}).agent_max_steps == 6


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENT_MAX_STEPS", "0"),
        ("AGENT_MAX_STEPS", "cuatro"),
        ("KB_MIN_SCORE", "0"),
        ("KB_MAX_RESULTS", "-1"),
        ("MAX_QUESTION_CHARS", "0"),
        ("MODEL_PROVIDER", "unknown-provider"),
        ("KB_PATH", "data/does-not-exist.json"),
    ],
)
def test_invalid_value_prevents_startup_with_a_clear_message(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_observability_settings_have_safe_defaults_and_reject_invalid_values():
    settings = load_settings({})
    assert settings.service_name == "support-assistant"
    # spec/06-traces.md: la meta pasa de 2000 a 4000 (dos llamadas al modelo real).
    assert settings.slo_p95_ms == 4000
    assert settings.log_conversation_text is True
    assert settings.langsmith_tracing is False
    assert (settings.hide_inputs, settings.hide_outputs) == (True, True)
    assert settings.tracing_enabled is False
    private = load_settings({"LOG_CONVERSATION_TEXT": "false"})
    assert private.log_conversation_text is False
    invalid = (
        ("SLO_P95_MS", "0"),
        ("LOG_CONVERSATION_TEXT", "quizas"),
        ("HIDE_INPUTS", "1"),
    )
    for name, value in invalid:
        with pytest.raises(ConfigError, match=name):
            load_settings({name: value})


def test_langsmith_project_defaults_to_support_assistant_and_must_not_be_empty():
    assert load_settings({}).langsmith_project == "support-assistant"
    custom = load_settings({"LANGSMITH_PROJECT": "help-desk-traces"})
    assert custom.langsmith_project == "help-desk-traces"
    with pytest.raises(ConfigError, match="LANGSMITH_PROJECT"):
        load_settings({"LANGSMITH_PROJECT": "   "})


def test_env_example_lists_every_setting_with_its_default_and_empty_secrets():
    active, commented = _env_example()
    for name, default in DEFAULTS.items():
        assert active.get(name) == default, name
    for name in SECRET_VARIABLES:
        assert active.get(name) == "", name
    assert active.get("LANGSMITH_PROJECT") == "support-assistant"
    assert active.get("SLO_P95_MS") == "4000"
    assert commented.get("LANGSMITH_ENDPOINT", "").startswith("https://")
    assert "LANGSMITH_ENDPOINT" not in active


def test_cost_settings_have_the_documented_defaults():
    settings = load_settings({})
    assert (settings.cf_account_id, settings.cf_gateway_id) == ("", "default")
    assert settings.cf_api_token == ""
    assert settings.model_small == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert settings.model_large == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0
    assert settings.cache_ttl_seconds == 0
    prices_path = Path(settings.prices_path)
    assert prices_path.is_file()
    assert prices_path.parts[-2:] == ("data", "model_prices.json")
    assert load_settings({"HISTORY_WINDOW": "0"}).history_window == 0
    assert load_settings({"MODEL_TEMPERATURE": "0.7"}).model_temperature == 0.7


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ROUTER_MAX_CHARS", "0"),
        ("ROUTER_MAX_CHARS", "ochenta"),
        ("HISTORY_WINDOW", "-1"),
        ("MODEL_MAX_TOKENS", "0"),
        ("MODEL_TEMPERATURE", "x"),
        ("CACHE_TTL_SECONDS", "-1"),
        ("ROUTING", "si"),
        ("MODEL_SMALL", " "),
        ("PRICES_PATH", "data/does-not-exist.json"),
    ],
)
def test_invalid_cost_setting_prevents_startup_naming_the_variable(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


@pytest.mark.parametrize("missing", ["CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN"])
def test_gateway_needs_each_cloudflare_variable_and_never_shows_secrets(missing):
    environ = {
        "MODEL_PROVIDER": "gateway",
        "CF_ACCOUNT_ID": ACCOUNT,
        "CF_GATEWAY_ID": "help-desk-gateway",
        "CF_API_TOKEN": TOKEN,
    }
    settings = load_settings(environ)
    assert settings.model_provider == "gateway"
    assert ACCOUNT not in repr(settings)
    assert TOKEN not in repr(settings)
    with pytest.raises(ConfigError, match=missing) as caught:
        load_settings({**environ, missing: ""})
    assert ACCOUNT not in str(caught.value)
    assert TOKEN not in str(caught.value)


def test_production_settings_have_closed_defaults_and_never_show_the_keys():
    defaults = load_settings({})
    assert defaults.environment == "development"
    assert not defaults.api_keys
    assert defaults.rate_limit_per_minute == 30
    keyed = load_settings({"API_KEYS": f"support:{API_KEY}"})
    assert [client.name for client in keyed.api_keys] == ["support"]
    assert API_KEY not in repr(keyed)
    assert load_settings({"RATE_LIMIT_PER_MINUTE": "5"}).rate_limit_per_minute == 5


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ENVIRONMENT", "staging"),
        ("RATE_LIMIT_PER_MINUTE", "0"),
        ("RATE_LIMIT_PER_MINUTE", "treinta"),
    ],
)
def test_invalid_environment_or_rate_limit_prevents_startup(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_demo_settings_are_off_by_default_and_a_zero_budget_is_fine_without_demo():
    settings = load_settings({})
    assert (settings.public_page, settings.trust_proxy) == (False, False)
    assert settings.public_rate_limit_per_minute == 5
    assert settings.daily_budget_usd == 0.5
    demo = load_settings({"PUBLIC_PAGE": "true", "TRUST_PROXY": "TRUE"})
    assert (demo.public_page, demo.trust_proxy) == (True, True)
    assert load_settings({"DAILY_BUDGET_USD": "0"}).daily_budget_usd == 0


@pytest.mark.parametrize(
    ("environ", "name"),
    [
        ({"PUBLIC_PAGE": "si"}, "PUBLIC_PAGE"),
        ({"TRUST_PROXY": "1"}, "TRUST_PROXY"),
        ({"DAILY_BUDGET_USD": "medio"}, "DAILY_BUDGET_USD"),
        ({"DAILY_BUDGET_USD": "nan"}, "DAILY_BUDGET_USD"),
        ({"DAILY_BUDGET_USD": "inf"}, "DAILY_BUDGET_USD"),
        ({"PUBLIC_RATE_LIMIT_PER_MINUTE": "cinco"}, "PUBLIC_RATE_LIMIT_PER_MINUTE"),
        ({"PUBLIC_PAGE": "true", "DAILY_BUDGET_USD": "0"}, "DAILY_BUDGET_USD"),
        ({"PUBLIC_PAGE": "true", "DAILY_BUDGET_USD": "-1"}, "DAILY_BUDGET_USD"),
        (
            {"PUBLIC_PAGE": "true", "PUBLIC_RATE_LIMIT_PER_MINUTE": "0"},
            "PUBLIC_RATE_LIMIT_PER_MINUTE",
        ),
    ],
)
def test_invalid_demo_setting_prevents_startup_naming_the_variable(environ, name):
    with pytest.raises(ConfigError, match=name):
        load_settings(environ)


def test_public_client_name_is_reserved_when_the_demo_is_on():
    keys = {"API_KEYS": f"public:{API_KEY}"}
    assert [client.name for client in load_settings(keys).api_keys] == ["public"]
    with pytest.raises(ConfigError, match="API_KEYS") as caught:
        load_settings({**keys, "PUBLIC_PAGE": "true"})
    assert API_KEY not in str(caught.value)


@pytest.mark.usefixtures("restore_environ")
def test_env_file_is_read_relative_to_the_product_and_the_environment_wins(
    write_product_file, monkeypatch, tmp_path
):
    write_product_file("qa-relative.env", "ROUTER_MAX_CHARS=120\nHISTORY_WINDOW=2\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENV_FILE", "qa-relative.env")
    monkeypatch.delenv("ROUTER_MAX_CHARS", raising=False)
    monkeypatch.setenv("HISTORY_WINDOW", "4")
    settings = load_settings()
    assert settings.router_max_chars == 120
    assert settings.history_window == 4


@pytest.mark.usefixtures("restore_environ")
def test_env_file_is_skipped_when_missing_disabled_or_the_environment_is_given(
    write_product_file, monkeypatch, tmp_path
):
    write_product_file("none", "ROUTER_MAX_CHARS=120\n")
    write_product_file("qa-ignored.env", "ROUTER_MAX_CHARS=120\n")
    monkeypatch.delenv("ROUTER_MAX_CHARS", raising=False)
    for env_file in ("none", str(tmp_path / "missing.env")):
        monkeypatch.setenv("ENV_FILE", env_file)
        assert load_settings().router_max_chars == 80
    monkeypatch.setenv("ENV_FILE", "qa-ignored.env")
    assert load_settings({}).router_max_chars == 80
    assert load_settings({"ENV_FILE": "qa-ignored.env"}).router_max_chars == 80
    assert "ROUTER_MAX_CHARS" not in os.environ
