"""Pruebas unitarias de las claves por cliente (``app.security``).

Todas las claves son textos de ejemplo; ninguna es real.
"""

import hmac
import re

import pytest

from app import security
from app.config import ConfigError, load_settings
from app.security import ApiKeyAuthenticator, parse_api_keys

# Direcciones de documentación (RFC 5737): nunca de una persona real.
PEER = "203.0.113.5"
PROXIED = "192.0.2.1, 198.51.100.7"
ALPHA_KEY = "example-alpha-key-0001"
BETA_KEY = "example-beta-key-0002"
GAMMA_KEY = "example-gamma-key-0003"
NO_CLIENT_ENTRY = "secret-value-without-client"


def _clients():
    """Tres clientes de ejemplo."""
    return parse_api_keys(
        f"alpha:{ALPHA_KEY},beta:{BETA_KEY},gamma:{GAMMA_KEY}"
    )


def test_api_keys_are_parsed_into_named_clients():
    clients = parse_api_keys(f" alpha : {ALPHA_KEY} , beta:{BETA_KEY}:with-colon ")
    assert [(client.name, client.key) for client in clients] == [
        ("alpha", ALPHA_KEY),
        ("beta", f"{BETA_KEY}:with-colon"),
    ]
    single = parse_api_keys(f"alpha:{ALPHA_KEY}")
    assert [client.name for client in single] == ["alpha"]
    assert not parse_api_keys("")
    assert not parse_api_keys("   ")


@pytest.mark.parametrize(
    "raw",
    [
        f"alpha:{ALPHA_KEY},{NO_CLIENT_ENTRY}",
        f"alpha:{ALPHA_KEY}, :{BETA_KEY}",
        f"alpha:{ALPHA_KEY},beta:",
        f"alpha:{ALPHA_KEY},alpha:{BETA_KEY}",
        f"alpha:{ALPHA_KEY},beta:{ALPHA_KEY}",
    ],
    ids=["no-colon", "empty-client", "empty-key", "repeated-client", "repeated-key"],
)
def test_malformed_api_keys_name_the_entry_but_never_show_a_key(raw):
    with pytest.raises(ValueError, match=r"\b2\b") as caught:
        parse_api_keys(raw)
    message = str(caught.value)
    for secret in (ALPHA_KEY, BETA_KEY, NO_CLIENT_ENTRY):
        assert secret not in message
    assert caught.value.__cause__ is None


def test_an_entry_without_a_client_reports_its_length_and_prevents_startup():
    raw = f"alpha:{ALPHA_KEY},{NO_CLIENT_ENTRY}"
    length = re.escape(str(len(NO_CLIENT_ENTRY)))
    with pytest.raises(ConfigError, match=rf"API_KEYS.*\b{length}\b") as caught:
        load_settings({"API_KEYS": raw})
    assert NO_CLIENT_ENTRY not in str(caught.value)
    assert ALPHA_KEY not in str(caught.value)


def test_authenticator_identifies_only_an_exact_key():
    authenticator = ApiKeyAuthenticator(_clients())
    assert authenticator.identify(BETA_KEY) == "beta"
    assert authenticator.identify(GAMMA_KEY) == "gamma"
    for rejected in (None, "", "wrong-key", BETA_KEY + "x", BETA_KEY[:-1], "clave-ñ"):
        assert authenticator.identify(rejected) is None, rejected


def test_without_configured_keys_nobody_is_let_in():
    authenticator = ApiKeyAuthenticator(parse_api_keys(""))
    for header in (None, "", ALPHA_KEY):
        assert authenticator.identify(header) is None


def test_every_configured_key_is_compared_in_constant_time(monkeypatch):
    compared = []
    original = hmac.compare_digest

    def spy(first, second):
        compared.append(first)
        return original(first, second)

    monkeypatch.setattr(security.hmac, "compare_digest", spy)
    assert ApiKeyAuthenticator(_clients()).identify(ALPHA_KEY) == "alpha"
    assert len(compared) == 3


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "trust_proxy", "expected"),
    [
        (PEER, PROXIED, False, PEER),
        (PEER, None, True, PEER),
        (PEER, "198.51.100.7", True, "198.51.100.7"),
        (PEER, PROXIED, True, "198.51.100.7"),
        (PEER, "  198.51.100.7  ", True, "198.51.100.7"),
        (PEER, "", True, PEER),
        (PEER, "192.0.2.1, ", True, PEER),
        (None, None, False, "unknown"),
        (None, "", True, "unknown"),
    ],
    ids=[
        "untrusted-header-ignored",
        "trusted-without-header",
        "trusted-single-entry",
        "trusted-last-entry",
        "trusted-with-spaces",
        "trusted-empty-header",
        "trusted-empty-last-entry",
        "no-connection",
        "no-connection-empty-header",
    ],
)
def test_client_ip_is_the_connection_or_the_last_trusted_forwarded_entry(
    peer, forwarded_for, trust_proxy, expected
):
    assert security.resolve_client_ip(peer, forwarded_for, trust_proxy) == expected
    assert security.PUBLIC_CLIENT == "public"
