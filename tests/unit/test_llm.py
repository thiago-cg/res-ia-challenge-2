import logging
from types import SimpleNamespace

import httpx
import pytest

from src.generate.llm import (
    APILLM,
    LLMUnavailable,
    LocalLLM,
    MockLLM,
    get_llm,
)
from src.generate.prompt import PROMPT_VERSION
from src.generate.schemas import parse_llm_output


def test_mock_llm_is_deterministic_and_valid() -> None:
    client = MockLLM(context_ids=["lmp/art22", "lmp/art24"])

    first = client.complete("system", "user")
    second = client.complete("system", "user")

    assert first == second
    output = parse_llm_output(first)
    assert [citation.device_id for citation in output.citacoes] == ["lmp/art22", "lmp/art24"]
    assert client.model_name == "mock"
    assert client.version == PROMPT_VERSION


def test_mock_llm_never_invents_ids() -> None:
    client = MockLLM(context_ids=["lmp/art22"])

    output = parse_llm_output(client.complete("system", "user"))

    assert {citation.device_id for citation in output.citacoes} <= {"lmp/art22"}


def test_mock_llm_without_context_returns_no_citations() -> None:
    output = parse_llm_output(MockLLM().complete("system", "user"))

    assert output.citacoes == []


def test_mock_llm_context_can_change_between_calls() -> None:
    client = MockLLM(context_ids=["lmp/art22"])

    client.set_context_ids(["lmp/art24"])
    after_setter = parse_llm_output(client.complete("system", "user"))
    per_call = parse_llm_output(client.complete("system", "user", context_ids=["lmp/art25"]))

    assert [citation.device_id for citation in after_setter.citacoes] == ["lmp/art24"]
    assert [citation.device_id for citation in per_call.citacoes] == ["lmp/art25"]


def test_get_llm_selects_mock_by_default() -> None:
    client = get_llm(SimpleNamespace(llm_provider="mock"))

    assert isinstance(client, MockLLM)


def test_get_llm_selects_local_and_api() -> None:
    local = get_llm(
        SimpleNamespace(
            llm_provider="local",
            llm_base_url="http://local.test",
            llm_api_key="secret",
            llm_model="local-model",
        )
    )
    api = get_llm(
        SimpleNamespace(
            llm_provider="api",
            llm_base_url="http://api.test",
            llm_api_key="secret",
            llm_model="api-model",
        )
    )

    assert isinstance(local, LocalLLM)
    assert isinstance(api, APILLM)


def test_get_llm_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        get_llm(SimpleNamespace(llm_provider="nope"))


def test_local_and_api_require_base_url() -> None:
    with pytest.raises(ValueError):
        LocalLLM(base_url="", model_name="m")
    with pytest.raises(ValueError):
        APILLM(base_url="", api_key="key", model_name="m")


def test_local_llm_allows_keyless_ollama() -> None:
    client = LocalLLM(base_url="http://local.test", model_name="m")

    assert client._headers() == {"Content-Type": "application/json"}


def test_api_llm_requires_api_key() -> None:
    with pytest.raises(ValueError):
        APILLM(base_url="http://api.test", api_key="", model_name="m")


def make_openai_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_api_llm_retries_and_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("authorization", "").startswith("Bearer "))
        if len(calls) < 3:
            return httpx.Response(500, json={"error": "boom"})
        return make_openai_response("ok")

    client = APILLM(
        base_url="http://api.test",
        api_key="secret",
        model_name="m",
        backoff_base=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.complete("system", "user") == "ok"
    assert len(calls) == 3


def test_api_llm_retries_on_429() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return make_openai_response("ok")

    client = APILLM(
        base_url="http://api.test",
        api_key="secret",
        model_name="m",
        backoff_base=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.complete("system", "user") == "ok"
    assert calls == 2


def test_api_llm_timeout_raises_unavailable_after_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    client = APILLM(
        base_url="http://api.test",
        api_key="secret",
        model_name="m",
        backoff_base=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMUnavailable):
        client.complete("system", "user")
    assert calls == 3


def test_api_llm_client_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad request"})

    client = APILLM(
        base_url="http://api.test",
        api_key="secret",
        model_name="m",
        backoff_base=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMUnavailable):
        client.complete("system", "user")
    assert calls == 1


def test_local_llm_parses_ollama_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "resposta local"}})

    client = LocalLLM(
        base_url="http://local.test",
        model_name="m",
        backoff_base=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.complete("system", "user") == "resposta local"


def test_http_llm_closes_owned_client() -> None:
    client = APILLM(
        base_url="http://api.test",
        api_key="secret",
        model_name="m",
        backoff_base=0,
    )

    with client as managed:
        assert managed is client
    assert client._client.is_closed is True


def test_http_llm_does_not_close_injected_client() -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    client = APILLM(
        base_url="http://api.test",
        api_key="secret",
        model_name="m",
        client=http_client,
    )

    client.close()

    assert http_client.is_closed is False
    http_client.close()


def test_never_logs_prompt_or_credentials(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = APILLM(
        base_url="http://api.test",
        api_key="sk-super-secret",
        model_name="m",
        backoff_base=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMUnavailable):
        client.complete("system", "pergunta confidencial da usuária")

    assert "sk-super-secret" not in caplog.text
    assert "pergunta confidencial" not in caplog.text
