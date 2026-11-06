from __future__ import annotations

import os

import pytest

from src.generate.llm import OpenRouterLLM
from src.index.embed import OpenRouterEncoder

pytestmark = pytest.mark.integration

CHAT_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
EMBEDDING_MODEL = os.environ.get(
    "OPENROUTER_EMBEDDING_MODEL",
    "openai/text-embedding-3-small",
)
EMBEDDING_DIMENSIONS = int(os.environ.get("OPENROUTER_EMBEDDING_DIMENSIONS", "1024"))


@pytest.fixture(scope="module")
def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        pytest.skip("OPENROUTER_API_KEY is not set; live OpenRouter smoke was skipped")
    return key


def test_openrouter_chat_live(api_key: str) -> None:
    client = OpenRouterLLM(
        api_key=api_key,
        model_name=CHAT_MODEL,
        max_retries=0,
        backoff_base=0,
    )
    try:
        content = client.complete(
            "Responda apenas com JSON valido.",
            'Responda apenas com {"ok": true}.',
        )
    finally:
        client.close()

    assert content.strip()


def test_openrouter_embeddings_live(api_key: str) -> None:
    encoder = OpenRouterEncoder(
        model=EMBEDDING_MODEL,
        api_key=api_key,
        dimension=EMBEDDING_DIMENSIONS,
        batch_size=1,
        max_retries=0,
        backoff_base=0,
    )
    try:
        vector = encoder.encode_query("teste")
    finally:
        encoder.close()

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert any(value != 0.0 for value in vector)
