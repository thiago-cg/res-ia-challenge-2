from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from src.generate.llm import LLMUnavailable, OpenRouterLLM, get_llm


def _content_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _client(handler, **overrides) -> OpenRouterLLM:
    options = {
        "base_url": "https://openrouter.test/api/v1",
        "api_key": "test-key",
        "model_name": "openai/gpt-4o-mini",
        "backoff_base": 0,
        "client": httpx.Client(transport=httpx.MockTransport(handler)),
    }
    options.update(overrides)
    return OpenRouterLLM(**options)


def test_openrouter_llm_sends_openai_compatible_payload_and_headers() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return _content_response("ok")

    client = _client(handler, site_url="https://example.test", app_name="violencia")
    try:
        assert client.complete("sistema", "pergunta") == "ok"
    finally:
        client.close()

    assert captured["url"] == "https://openrouter.test/api/v1/chat/completions"
    headers = captured["headers"]
    assert headers["authorization"] == "Bearer test-key"
    assert headers["http-referer"] == "https://example.test"
    assert headers["x-title"] == "violencia"
    payload = captured["payload"]
    assert payload["model"] == "openai/gpt-4o-mini"
    assert payload["messages"] == [
        {"role": "system", "content": "sistema"},
        {"role": "user", "content": "pergunta"},
    ]


def test_openrouter_llm_omits_optional_headers_when_unset() -> None:
    seen: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return _content_response("ok")

    client = _client(handler)
    try:
        client.complete("system", "user")
    finally:
        client.close()

    assert "http-referer" not in seen["headers"]
    assert "x-title" not in seen["headers"]


def test_openrouter_llm_retries_429_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _content_response("ok")

    client = _client(handler)
    try:
        assert client.complete("system", "user") == "ok"
    finally:
        client.close()

    assert calls == 2


def test_openrouter_llm_retries_server_errors_up_to_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    client = _client(handler, max_retries=1)
    with pytest.raises(LLMUnavailable, match="status 503"):
        client.complete("system", "user")
    client.close()

    assert calls == 2


@pytest.mark.parametrize("status", [401, 402, 404])
def test_openrouter_llm_fails_clearly_without_retrying(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "denied"}})

    client = _client(handler)
    with pytest.raises(LLMUnavailable, match=f"status {status}"):
        client.complete("system", "user")
    client.close()

    assert calls == 1


def test_openrouter_llm_requires_api_key() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterLLM(
            base_url="https://openrouter.test/api/v1",
            api_key="",
            model_name="openai/gpt-4o-mini",
        )


def test_get_llm_openrouter_falls_back_to_llm_model() -> None:
    client = get_llm(
        SimpleNamespace(
            llm_provider="openrouter",
            openrouter_api_key="key",
            openrouter_base_url="https://openrouter.test/api/v1",
            openrouter_model="",
            llm_model="meta/llama-test",
        )
    )
    try:
        assert isinstance(client, OpenRouterLLM)
        assert client.model_name == "meta/llama-test"
    finally:
        client.close()


def test_get_llm_openrouter_uses_defaults_for_missing_attributes() -> None:
    client = get_llm(SimpleNamespace(llm_provider="openrouter", openrouter_api_key="key"))
    try:
        assert isinstance(client, OpenRouterLLM)
        assert client.model_name == "openai/gpt-4o-mini"
        assert client.base_url == "https://openrouter.ai/api/v1"
    finally:
        client.close()


def test_get_llm_openrouter_without_key_names_the_env_var() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_llm(SimpleNamespace(llm_provider="openrouter"))


def test_openrouter_llm_never_logs_key_or_prompt(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    client = _client(handler, api_key="sk-super-secret")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMUnavailable):
        client.complete("sistema", "pergunta confidencial da usuaria")
    client.close()

    assert "sk-super-secret" not in caplog.text
    assert "pergunta confidencial" not in caplog.text
