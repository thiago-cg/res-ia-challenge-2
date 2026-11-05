from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.contracts import ModelFormatError

LOCAL_06B_GGUF = (
    r"C:\Users\tito\.cache\huggingface\hub"
    r"\models--bigdawg003--pplx-embed-v2-late-0.6b-GGUF"
)
LOCAL_9B_GGUF = (
    r"C:\Users\tito\.cache\huggingface\hub"
    r"\models--antarrb--pplx-embed-v2-late-9b-GGUF"
)

GGUF_FIELDS = ("ppx_9b_model_path", "ppx_06b_model_path", "harrier_model_path")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    retrieval_path: Literal["fallback", "target"] = "fallback"
    embedding_provider: Literal["harrier", "pplx"] = "harrier"
    llm_provider: Literal["mock", "local", "api"] = "mock"

    max_devices: int = Field(default=10, gt=0)
    max_context_tokens: int = Field(default=6000, gt=0)
    max_subquestions: int = Field(default=3, gt=0)
    max_agent_loops: int = Field(default=3, gt=0)

    database_url: str = "postgresql://app:app@localhost:5432/violencia"
    qdrant_url: str = "http://localhost:6333"

    ppx_9b_model_path: str = ""
    ppx_06b_model_path: str = ""
    harrier_model_path: str = ""
    llm_model: str = ""
    log_level: str = "INFO"

    @model_validator(mode="after")
    def reject_gguf_models(self) -> "Settings":
        for field in GGUF_FIELDS:
            value = getattr(self, field)
            if value and value.lower().endswith(".gguf"):
                raise ModelFormatError(
                    f"{field}={value!r} is a GGUF (llama.cpp) artifact; "
                    "sentence-transformers cannot load it. "
                    "Point the setting at a safetensors model directory or use the fallback path. "
                    f"Local GGUF artifacts: {LOCAL_06B_GGUF} and {LOCAL_9B_GGUF}."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
