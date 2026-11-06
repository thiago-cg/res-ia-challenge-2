from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.generate.llm import OpenRouterLLM, get_llm
from src.index.embed import OpenRouterEncoder, get_encoder


def test_openrouter_settings_defaults_do_not_require_a_key() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_provider == "mock"
    assert settings.embedding_provider == "harrier"
    assert settings.openrouter_api_key == ""
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.openrouter_model == "openai/gpt-4o-mini"
    assert settings.openrouter_embedding_model == "openai/text-embedding-3-small"
    assert settings.openrouter_embedding_dimensions == 1024
    assert settings.openrouter_batch_size == 32
    assert settings.openrouter_timeout == 60.0
    assert settings.openrouter_max_retries == 2
    assert settings.openrouter_data_collection == "deny"
    assert settings.openrouter_zdr is True
    assert settings.openrouter_site_url == ""
    assert settings.openrouter_app_name == ""
    assert settings.llm_base_url == ""
    assert settings.llm_api_key == ""


def test_openrouter_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "meta/llama-test")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-large")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("OPENROUTER_BATCH_SIZE", "8")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "12.5")
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", "0")
    monkeypatch.setenv("OPENROUTER_DATA_COLLECTION", "allow")
    monkeypatch.setenv("OPENROUTER_ZDR", "false")
    monkeypatch.setenv("OPENROUTER_SITE_URL", "https://example.test")
    monkeypatch.setenv("OPENROUTER_APP_NAME", "violencia")
    monkeypatch.setenv("LLM_BASE_URL", "http://local.test")
    monkeypatch.setenv("LLM_API_KEY", "local-key")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openrouter"
    assert settings.embedding_provider == "openrouter"
    assert settings.openrouter_api_key == "env-key"
    assert settings.openrouter_base_url == "https://proxy.test/v1"
    assert settings.openrouter_model == "meta/llama-test"
    assert settings.openrouter_embedding_model == "openai/text-embedding-3-large"
    assert settings.openrouter_embedding_dimensions == 768
    assert settings.openrouter_batch_size == 8
    assert settings.openrouter_timeout == 12.5
    assert settings.openrouter_max_retries == 0
    assert settings.openrouter_data_collection == "allow"
    assert settings.openrouter_zdr is False
    assert settings.openrouter_site_url == "https://example.test"
    assert settings.openrouter_app_name == "violencia"
    assert settings.llm_base_url == "http://local.test"
    assert settings.llm_api_key == "local-key"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_provider", "openai"),
        ("llm_provider", "cloud"),
        ("openrouter_data_collection", "maybe"),
        ("openrouter_embedding_dimensions", 0),
        ("openrouter_batch_size", 0),
        ("openrouter_timeout", 0),
        ("openrouter_max_retries", -1),
    ],
)
def test_invalid_openrouter_settings_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_openrouter_selection_defers_missing_key_to_client_construction() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openrouter",
        embedding_provider="openrouter",
    )

    assert settings.openrouter_api_key == ""
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_llm(settings)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_encoder(settings)


def test_openrouter_clients_are_built_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openrouter",
        embedding_provider="openrouter",
        openrouter_api_key="test-key",
    )

    llm = get_llm(settings)
    encoder = get_encoder(settings)
    try:
        assert isinstance(llm, OpenRouterLLM)
        assert isinstance(encoder, OpenRouterEncoder)
        assert llm.model_name == "openai/gpt-4o-mini"
        assert encoder.model_name == "openai/text-embedding-3-small"
        assert encoder.dimension == 1024
        assert encoder.revision == "openrouter:openai/text-embedding-3-small"
    finally:
        llm.close()
        encoder.close()
