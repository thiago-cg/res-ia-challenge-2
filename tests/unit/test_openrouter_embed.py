from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from src.api.main import build_default_pipeline
from src.config import Settings
from src.index.embed import EmbeddingUnavailable, OpenRouterEncoder, get_encoder


def _embedding_response(vectors: list[list[float]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [{"index": index, "embedding": vector} for index, vector in enumerate(vectors)]
        },
    )


def _encoder(handler, **overrides) -> OpenRouterEncoder:
    options = {
        "model": "openai/text-embedding-3-small",
        "api_key": "test-key",
        "base_url": "https://openrouter.test/api/v1",
        "dimension": 3,
        "batch_size": 2,
        "backoff_base": 0,
        "client": httpx.Client(transport=httpx.MockTransport(handler)),
    }
    options.update(overrides)
    return OpenRouterEncoder(**options)


def test_openrouter_encoder_splits_batches_and_sends_dimensions() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        assert request.url == "https://openrouter.test/api/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-key"
        return _embedding_response([[0.1, 0.2, 0.3] for _ in payload["input"]])

    encoder = _encoder(handler, data_collection="allow", zdr=False)
    try:
        vectors = encoder.encode_documents(["a", "b", "c", "d", "e"])
    finally:
        encoder.close()

    assert len(vectors) == 5
    assert [len(payload["input"]) for payload in payloads] == [2, 2, 1]
    assert all(payload["model"] == "openai/text-embedding-3-small" for payload in payloads)
    assert all(payload["dimensions"] == 3 for payload in payloads)
    assert all(payload["encoding_format"] == "float" for payload in payloads)
    assert all(
        payload["provider"] == {"data_collection": "allow", "zdr": False, "allow_fallbacks": True}
        for payload in payloads
    )


def test_openrouter_encoder_defaults_to_private_provider_preferences() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _embedding_response([[1.0, 0.0, 0.0]])

    encoder = _encoder(handler)
    try:
        encoder.encode_documents(["texto"])
    finally:
        encoder.close()

    assert seen[0]["provider"] == {
        "data_collection": "deny",
        "zdr": True,
        "allow_fallbacks": True,
    }


def test_openrouter_encoder_sends_optional_headers() -> None:
    seen: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return _embedding_response([[1.0, 0.0, 0.0]])

    encoder = _encoder(
        handler,
        site_url="https://example.test",
        app_name="violencia",
    )
    try:
        encoder.encode_query("teste")
    finally:
        encoder.close()

    assert seen["headers"]["http-referer"] == "https://example.test"
    assert seen["headers"]["x-title"] == "violencia"


def test_openrouter_encoder_query_returns_single_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _embedding_response([[0.4, 0.5, 0.6]])

    encoder = _encoder(handler)
    try:
        vector = encoder.encode_query("teste")
    finally:
        encoder.close()

    assert vector == [0.4, 0.5, 0.6]


def test_openrouter_encoder_orders_vectors_by_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [2.0, 0.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ]
            },
        )

    encoder = _encoder(handler)
    try:
        vectors = encoder.encode_documents(["a", "b"])
    finally:
        encoder.close()

    assert vectors == [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]


def test_openrouter_encoder_validates_vector_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _embedding_response([[0.1, 0.2]])

    encoder = _encoder(handler)
    with pytest.raises(ValueError, match="OPENROUTER_EMBEDDING_DIMENSIONS") as excinfo:
        encoder.encode_documents(["texto"])
    encoder.close()

    assert "2" in str(excinfo.value)
    assert "3" in str(excinfo.value)


def test_openrouter_encoder_retries_429_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _embedding_response([[0.1, 0.2, 0.3]])

    encoder = _encoder(handler)
    try:
        assert encoder.encode_query("teste") == [0.1, 0.2, 0.3]
    finally:
        encoder.close()

    assert calls == 2


def test_openrouter_encoder_retries_server_errors_up_to_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, json={"error": {"message": "bad gateway"}})

    encoder = _encoder(handler, max_retries=1)
    with pytest.raises(EmbeddingUnavailable, match="status 502"):
        encoder.encode_query("teste")
    encoder.close()

    assert calls == 2


@pytest.mark.parametrize("status", [401, 402, 404])
def test_openrouter_encoder_fails_clearly_without_retrying(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "denied"}})

    encoder = _encoder(handler)
    with pytest.raises(EmbeddingUnavailable, match=f"status {status}"):
        encoder.encode_query("teste")
    encoder.close()

    assert calls == 1


def test_openrouter_encoder_retries_timeouts() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return _embedding_response([[0.1, 0.2, 0.3]])

    encoder = _encoder(handler)
    try:
        assert encoder.encode_query("teste") == [0.1, 0.2, 0.3]
    finally:
        encoder.close()

    assert calls == 2


def test_openrouter_encoder_requires_api_key() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterEncoder(model="openai/text-embedding-3-small", api_key="")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_encoder(
            Settings(
                _env_file=None,
                embedding_provider="openrouter",
                openrouter_api_key="",
            )
        )


def test_get_encoder_openrouter_does_not_require_a_pinned_revision() -> None:
    settings = Settings(
        _env_file=None,
        embedding_provider="openrouter",
        embedding_model_revision="",
        openrouter_api_key="key",
    )

    encoder = get_encoder(settings)

    assert isinstance(encoder, OpenRouterEncoder)
    assert encoder.revision == "openrouter:openai/text-embedding-3-small"
    encoder.close()


def test_get_encoder_openrouter_uses_configured_values() -> None:
    settings = Settings(
        _env_file=None,
        embedding_provider="openrouter",
        openrouter_api_key="key",
        openrouter_embedding_model="qwen/qwen3-embedding-8b",
        openrouter_embedding_dimensions=8,
        openrouter_batch_size=4,
    )

    encoder = get_encoder(settings)
    try:
        assert encoder.model_name == "qwen/qwen3-embedding-8b"
        assert encoder.dimension == 8
        assert encoder.batch_size == 4
    finally:
        encoder.close()


def test_openrouter_encoder_handles_empty_input() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _embedding_response([])

    encoder = _encoder(handler)
    try:
        assert encoder.encode_documents([]) == []
    finally:
        encoder.close()

    assert calls == 0


def test_openrouter_encoder_closes_only_owned_clients() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _embedding_response([[0.1, 0.2, 0.3]])

    injected = httpx.Client(transport=httpx.MockTransport(handler))
    encoder = _encoder(handler, client=injected)
    encoder.close()
    assert injected.is_closed is False
    injected.close()

    owned = OpenRouterEncoder(
        model="openai/text-embedding-3-small",
        api_key="key",
        dimension=3,
        backoff_base=0,
    )
    owned.close()
    assert owned._client.is_closed is True


def test_openrouter_encoder_never_logs_key_or_text(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    encoder = _encoder(handler, api_key="sk-super-secret")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(EmbeddingUnavailable):
        encoder.encode_query("pergunta confidencial da usuaria")
    encoder.close()

    assert "sk-super-secret" not in caplog.text
    assert "pergunta confidencial" not in caplog.text


def test_build_default_pipeline_rejects_openrouter_target_path() -> None:
    settings = Settings(
        _env_file=None,
        embedding_provider="openrouter",
        retrieval_path="target",
        openrouter_api_key="key",
    )

    with pytest.raises(ValueError, match="multivector") as excinfo:
        build_default_pipeline(settings, None)

    assert "RETRIEVAL_PATH=fallback" in str(excinfo.value)


def test_get_encoder_keeps_harrier_behavior_without_openrouter_settings() -> None:
    settings = Settings(
        _env_file=None,
        embedding_provider="harrier",
        harrier_model_path="/models/harrier",
        embedding_model_revision="rev-1",
    )

    encoder = get_encoder(settings)

    assert encoder.model_name == "/models/harrier"
    assert encoder.revision == "rev-1"


def test_get_encoder_openrouter_ignores_local_model_paths() -> None:
    fake = SimpleNamespace(
        embedding_provider="openrouter",
        openrouter_api_key="key",
        openrouter_embedding_model="openai/text-embedding-3-small",
        openrouter_embedding_dimensions=4,
    )

    encoder = get_encoder(fake)
    try:
        assert encoder.dimension == 4
    finally:
        encoder.close()


def test_query_instruction_is_prepended_only_to_queries() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _embedding_response([[1.0, 0.0, 0.0]])

    encoder = _encoder(handler, query_instruction="Instruct: x Query: ")
    try:
        encoder.encode_documents(["documento"])
        encoder.encode_query("pergunta")
    finally:
        encoder.close()

    assert seen[0]["input"] == ["documento"]
    assert seen[1]["input"] == ["Instruct: x Query: pergunta"]
