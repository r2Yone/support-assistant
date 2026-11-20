"""Pruebas unitarias del modelo real (Workers AI vía AI Gateway) sin red."""

import json

import httpx
import pytest

from app.gateway import GatewayModel, ModelUnavailable

MODEL_NAME = "@cf/meta/llama-3.1-8b-instruct-fast"
CONVERSATION = [{"role": "user", "content": "Mi laptop no enciende"}]
PROMPT_TERMS = (
    "search_knowledge_base",
    "escalate_to_human",
    "problem",
    "category",
    "JSON",
    "español",
)


def _gateway(stub, cache_ttl_seconds=0):
    """Un ``GatewayModel`` con la cuenta del gateway simulado.

    :param stub: Gateway simulado.
    :param cache_ttl_seconds: Valor de ``CACHE_TTL_SECONDS``.
    :return: El modelo listo para llamar.
    """
    return GatewayModel(
        name=MODEL_NAME,
        account_id=stub.account,
        gateway_id=stub.gateway,
        api_token=stub.token,
        max_tokens=123,
        temperature=0.2,
        cache_ttl_seconds=cache_ttl_seconds,
        http_client=stub.client(),
    )


def test_gateway_posts_one_request_with_the_system_prompt_and_configured_body(
    gateway_stub,
):
    stub = gateway_stub(gateway_stub.reply('{"answer": "Listo"}'))
    completion = _gateway(stub).complete([dict(m) for m in CONVERSATION])
    assert json.loads(completion.text) == {"answer": "Listo"}
    assert len(stub.requests) == 1
    request = stub.requests[0]
    assert request.method == "POST"
    assert str(request.url) == (
        f"https://gateway.ai.cloudflare.com/v1/{stub.account}/{stub.gateway}"
        "/workers-ai/v1/chat/completions"
    )
    assert request.headers["Authorization"] == f"Bearer {stub.token}"
    body = stub.bodies()[0]
    assert set(body) == {"model", "messages", "max_tokens", "temperature"}
    assert (body["model"], body["max_tokens"], body["temperature"]) == (
        MODEL_NAME,
        123,
        0.2,
    )
    system, *conversation = body["messages"]
    assert system["role"] == "system"
    for term in PROMPT_TERMS:
        assert term in system["content"]
    assert conversation == CONVERSATION


def test_gateway_sends_the_token_for_the_authenticated_gateway_and_never_shows_it(
    gateway_stub,
):
    stub = gateway_stub(
        gateway_stub.reply('{"answer": "Listo"}'), gateway_stub.failure(401)
    )
    model = _gateway(stub)
    model.complete(CONVERSATION)
    headers = stub.requests[0].headers
    assert headers["cf-aig-authorization"] == f"Bearer {stub.token}"
    assert headers["Authorization"] == f"Bearer {stub.token}"
    assert stub.token not in repr(model)
    with pytest.raises(ModelUnavailable) as caught:
        model.complete(CONVERSATION)
    assert stub.token not in f"{caught.value} {caught.value!r}"
    assert stub.requests[1].headers["cf-aig-authorization"] == f"Bearer {stub.token}"


@pytest.mark.parametrize(
    ("ttl", "expected_header"),
    [(0, None), (300, "300")],
    ids=["cache-off", "cache-on"],
)
def test_gateway_sends_the_cache_ttl_header_only_when_the_ttl_is_positive(
    gateway_stub, ttl, expected_header
):
    stub = gateway_stub(gateway_stub.reply('{"answer": "Listo"}'))
    _gateway(stub, cache_ttl_seconds=ttl).complete(CONVERSATION)
    assert stub.requests[0].headers.get("cf-aig-cache-ttl") == expected_header


def test_gateway_reads_the_usage_tokens_and_marks_cache_hits(gateway_stub):
    stub = gateway_stub(
        gateway_stub.reply('{"answer": "A"}', 42, 7, cache_status="HIT"),
        gateway_stub.reply('{"answer": "B"}', 30, 5, cache_status="MISS"),
        gateway_stub.reply('{"answer": "C"}', 20, 3),
    )
    model = _gateway(stub, cache_ttl_seconds=60)
    hit, miss, plain = (model.complete(CONVERSATION) for _ in range(3))
    assert (hit.input_tokens, hit.output_tokens, hit.cached) == (42, 7, True)
    assert (miss.input_tokens, miss.output_tokens, miss.cached) == (30, 5, False)
    assert (plain.input_tokens, plain.output_tokens, plain.cached) == (20, 3, False)


@pytest.mark.parametrize(
    "kind",
    ["network", "timeout", "server-error", "unauthorized", "not-json", "no-choices"],
)
def test_gateway_failure_raises_model_unavailable_without_secrets_or_retries(
    gateway_stub, kind
):
    replies = {
        "network": httpx.ConnectError(
            f"cannot reach /v1/{gateway_stub.account}/ {gateway_stub.secret_body}"
        ),
        "timeout": httpx.ReadTimeout(f"timed out for {gateway_stub.account}"),
        "server-error": gateway_stub.failure(500),
        "unauthorized": gateway_stub.failure(401),
        "not-json": httpx.Response(200, text=f"<html>{gateway_stub.secret_body}"),
        "no-choices": httpx.Response(200, json={"error": gateway_stub.secret_body}),
    }
    stub = gateway_stub(replies[kind])
    with pytest.raises(ModelUnavailable) as caught:
        _gateway(stub).complete(CONVERSATION)
    error = caught.value
    shown = f"{error} {error!r} {error.error_type}"
    for secret in (stub.account, stub.token, stub.secret_body):
        assert secret not in shown
    assert isinstance(error.error_type, str) and error.error_type
    assert error.__cause__ is None
    assert len(stub.requests) == 1
