"""Pruebas unitarias de ``scripts/smoke.py`` con ``httpx.MockTransport`` (nunca red).

Desde ``spec/05-demo.md`` la segunda comprobación manda una clave equivocada (al azar)
y espera ``401``: así sirve con y sin modo demo.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

SMOKE_FILE = Path(__file__).resolve().parent.parent / "scripts" / "smoke.py"
API_KEY_HEADER = "X-API-Key"
URL = "https://support-assistant.example.test"
# Texto de ejemplo: nunca una clave real.
SMOKE_KEY = "example-smoke-key-0123456789"


@pytest.fixture
def smoke():
    """El módulo ``scripts/smoke.py``, cargado desde su archivo."""
    spec = importlib.util.spec_from_file_location("smoke", SMOKE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DemoServer:
    """Servicio simulado en modo demo: ``/ask`` sin clave también responde ``200``.

    :param accept_any_key: Si ``True``, acepta cualquier clave (un servicio roto).
    :type accept_any_key: bool
    """

    def __init__(self, accept_any_key=False):
        self.accept_any_key = accept_any_key
        self.sent_keys = []

    def handle(self, request):
        """Atiende una petición del ``MockTransport``.

        :param request: La petición de la prueba de humo.
        :type request: httpx.Request
        :return: ``200`` o ``401`` según la clave.
        :rtype: httpx.Response
        """
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        key = request.headers.get(API_KEY_HEADER)
        self.sent_keys.append(key)
        if key is None or key == SMOKE_KEY or self.accept_any_key:
            return httpx.Response(200, json={"answer": "Revisa la VPN"})
        return httpx.Response(401, json={"detail": "invalid or missing API key"})

    def client(self):
        """Un ``httpx.Client`` que solo habla con este servicio simulado.

        :return: El cliente HTTP.
        :rtype: httpx.Client
        """
        return httpx.Client(transport=httpx.MockTransport(self.handle))


def test_smoke_expects_401_from_a_random_wrong_key_and_never_prints_a_key(
    smoke, capsys
):
    server = DemoServer()
    assert smoke.run_checks(URL, SMOKE_KEY, server.client()) is True
    assert smoke.run_checks(URL, SMOKE_KEY, server.client()) is True
    assert len(server.sent_keys) == 4
    wrong_keys = server.sent_keys[0::2]
    assert server.sent_keys[1::2] == [SMOKE_KEY, SMOKE_KEY]
    for wrong in wrong_keys:
        assert wrong
        assert wrong != SMOKE_KEY
    assert wrong_keys[0] != wrong_keys[1]
    output = capsys.readouterr().out
    assert "[FAIL]" not in output
    for secret in (SMOKE_KEY, *wrong_keys):
        assert secret not in output


def test_smoke_fails_when_the_service_accepts_a_wrong_key(smoke, capsys):
    server = DemoServer(accept_any_key=True)
    assert smoke.run_checks(URL, SMOKE_KEY, server.client()) is False
    output = capsys.readouterr().out
    assert "[FAIL]" in output
    assert SMOKE_KEY not in output
    assert server.sent_keys[0] not in output


def test_smoke_without_the_key_variable_prints_the_usage_and_returns_2(
    smoke, capsys, monkeypatch
):
    monkeypatch.delenv(smoke.API_KEY_VARIABLE, raising=False)
    assert smoke.main([URL]) == 2
    monkeypatch.setenv(smoke.API_KEY_VARIABLE, SMOKE_KEY)
    assert smoke.main([]) == 2
    output = capsys.readouterr().out
    assert smoke.API_KEY_VARIABLE in output
    assert SMOKE_KEY not in output
