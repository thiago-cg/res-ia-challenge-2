import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings
from src.contracts import ModelFormatError

LOCAL_06B = (
    r"C:\Users\tito\.cache\huggingface\hub"
    r"\models--bigdawg003--pplx-embed-v2-late-0.6b-GGUF"
)
LOCAL_9B = (
    r"C:\Users\tito\.cache\huggingface\hub"
    r"\models--antarrb--pplx-embed-v2-late-9b-GGUF"
)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_match_plan() -> None:
    settings = Settings(_env_file=None)
    assert settings.retrieval_path == "fallback"
    assert settings.embedding_provider == "harrier"
    assert settings.llm_provider == "mock"
    assert settings.max_devices == 10
    assert settings.max_context_tokens == 6000
    assert settings.max_subquestions == 3
    assert settings.max_agent_loops == 3
    assert settings.database_url.startswith("postgresql://")
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.log_level == "INFO"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retrieval_path", "hybrid"),
        ("embedding_provider", "openai"),
        ("llm_provider", "cloud"),
    ],
)
def test_invalid_enums_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("field", ["max_devices", "max_context_tokens", "max_subquestions"])
def test_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_PATH", "target")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "pplx")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("MAX_DEVICES", "4")
    monkeypatch.setenv("MAX_SUBQUESTIONS", "2")

    settings = Settings(_env_file=None)
    assert settings.retrieval_path == "target"
    assert settings.embedding_provider == "pplx"
    assert settings.llm_provider == "local"
    assert settings.max_devices == 4
    assert settings.max_subquestions == 2


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


@pytest.mark.parametrize(
    "field",
    ["ppx_9b_model_path", "ppx_06b_model_path", "harrier_model_path"],
)
def test_gguf_paths_raise_actionable_error(field: str) -> None:
    with pytest.raises(ModelFormatError) as excinfo:
        Settings(_env_file=None, **{field: "/models/pplx-late-Q8_0.gguf"})

    message = str(excinfo.value)
    assert ".gguf" in message
    assert "safetensors" in message
    assert "fallback" in message
    assert LOCAL_9B in message
    assert LOCAL_06B in message


def test_safetensors_path_is_accepted() -> None:
    settings = Settings(
        _env_file=None,
        ppx_9b_model_path="/models/pplx-late-9b",
        harrier_model_path="/models/harrier-oss-v1-0.6b",
    )
    assert settings.ppx_9b_model_path == "/models/pplx-late-9b"
