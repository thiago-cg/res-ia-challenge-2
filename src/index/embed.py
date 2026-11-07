"""Embedding adapters for the fallback (Harrier) and target (PPLX) paths.

Local artifacts under ``src/config.py`` are GGUF only.  ``sentence-transformers``
cannot load GGUF, so the adapters import it lazily and reject ``.gguf`` paths
with an actionable ``ModelFormatError`` before any model work happens.

Harrier is instruction-aware: the instruction is prepended to the *query* only,
never to indexed documents (docs/05 §6).

The literal text is never modified here; ``embed_chunks`` only reads
``chunk.texto_indexacao`` and records the model, revision and text hash.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Iterable
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel

from src.config import LOCAL_06B_GGUF, LOCAL_9B_GGUF
from src.contracts import ModelFormatError
from src.index.chunk import Chunk

logger = logging.getLogger(__name__)

DEFAULT_HARRIER_MODEL = "microsoft/harrier-oss-v1-0.6b"
DEFAULT_PPLX_06B_MODEL = "perplexity-ai/pplx-embed-v2-late-0.6b"
DEFAULT_PPLX_9B_MODEL = "perplexity-ai/pplx-embed-v2-late-9b"
DEFAULT_DIMENSION = 1024
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openai/text-embedding-3-small"

HARRIER_INSTRUCTION = (
    "Instruct: Dada uma pergunta de uma vítima de violência doméstica, "
    "recupere o dispositivo legal que a responde.\nQuery: "
)
QUERY_INSTRUCTION = HARRIER_INSTRUCTION


class EmbeddingUnavailable(Exception):
    """Raised when the embedding provider cannot produce vectors after retries."""


class Encoder(Protocol):
    model_name: str
    revision: str
    dimension: int

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...

    def encode_query(self, text: str) -> list[float] | list[list[float]]: ...


class EmbeddedChunk(BaseModel):
    chunk: Chunk
    embedding: list[float]
    model: str
    revision: str
    text_hash: str

    @property
    def device_id(self) -> str:
        return self.chunk.device_id


class MockEncoder:
    """Deterministic hash-based encoder for unit tests (no model download)."""

    def __init__(
        self,
        dimension: int = DEFAULT_DIMENSION,
        *,
        model_name: str = "mock",
        revision: str = "mock",
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self.model_name = model_name
        self.revision = revision

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def encode_query(self, text: str) -> list[float]:
        return self._encode_one(text)

    def _encode_one(self, text: str) -> list[float]:
        raw = hashlib.shake_256(text.encode("utf-8")).digest(self.dimension * 4)
        values = [
            int.from_bytes(raw[index : index + 4], "big") / 2**32 * 2.0 - 1.0
            for index in range(0, len(raw), 4)
        ]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class _SentenceTransformerEncoder:
    def __init__(
        self,
        model_name: str,
        *,
        revision: str | None = None,
        dimension: int = DEFAULT_DIMENSION,
        model: Any | None = None,
        batch_size: int = 32,
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.model_name = model_name
        self.revision = _require_revision(revision)
        self.dimension = dimension
        self.batch_size = batch_size
        self._model = model

    def _get_model(self) -> Any:
        if self._model is None:
            self._model = _load_sentence_transformer(self.model_name, self.revision)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._get_model().encode(
            texts,
            normalize_embeddings=True,
            batch_size=self.batch_size,
            convert_to_numpy=True,
        )
        return [[float(value) for value in vector] for vector in vectors]


class HarrierEncoder(_SentenceTransformerEncoder):
    def __init__(
        self,
        model_path: str = "",
        *,
        revision: str | None = None,
        dimension: int = DEFAULT_DIMENSION,
        model: Any | None = None,
        batch_size: int = 32,
    ) -> None:
        _reject_gguf("harrier_model_path", model_path)
        super().__init__(
            model_path or DEFAULT_HARRIER_MODEL,
            revision=revision,
            dimension=dimension,
            model=model,
            batch_size=batch_size,
        )

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(list(texts))

    def encode_query(self, text: str) -> list[float]:
        return self._encode([HARRIER_INSTRUCTION + text])[0]


class PPLXEncoder(_SentenceTransformerEncoder):
    def __init__(
        self,
        model_path: str = "",
        *,
        revision: str | None = None,
        dimension: int = DEFAULT_DIMENSION,
        model: Any | None = None,
        batch_size: int = 32,
        settings_field: str | None = None,
    ) -> None:
        field = settings_field or _pplx_field_for(model_path)
        _reject_gguf(field, model_path)
        super().__init__(
            model_path or DEFAULT_PPLX_06B_MODEL,
            revision=revision,
            dimension=dimension,
            model=model,
            batch_size=batch_size,
        )

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(list(texts))

    def encode_query(self, text: str) -> list[float]:
        return self._encode([text])[0]


class OpenRouterEncoder:
    """Dense embeddings through OpenRouter's OpenAI-compatible API.

    OpenRouter only exposes dense embedding models; the pplx-v2-late
    multivector models used by the target path are not available.
    """

    def __init__(
        self,
        model: str = OPENROUTER_DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        base_url: str = OPENROUTER_DEFAULT_BASE_URL,
        dimension: int = DEFAULT_DIMENSION,
        batch_size: int = 32,
        timeout: float = 60.0,
        max_retries: int = 2,
        data_collection: Literal["deny", "allow"] = "deny",
        zdr: bool = True,
        site_url: str = "",
        app_name: str = "",
        query_instruction: str = "",
        backoff_base: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required for EMBEDDING_PROVIDER=openrouter; "
                "set it in the environment or in .env."
            )
        if not model:
            raise ValueError("embedding model is required")
        if not base_url:
            raise ValueError("embedding base_url is required")
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        self.model_name = model
        self.revision = f"openrouter:{model}"
        self.dimension = dimension
        self.batch_size = batch_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.data_collection = data_collection
        self.zdr = zdr
        self.site_url = site_url
        self.app_name = app_name
        self.query_instruction = query_instruction
        self.backoff_base = backoff_base
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client()

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/embeddings"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name
        return headers

    def _payload(self, batch: list[str]) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "input": batch,
            "dimensions": self.dimension,
            "encoding_format": "float",
            "provider": {
                "data_collection": self.data_collection,
                "zdr": self.zdr,
                "allow_fallbacks": True,
            },
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenRouterEncoder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        items = list(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            vectors.extend(self._encode_batch(batch))
        return vectors

    def encode_query(self, text: str) -> list[float]:
        query = f"{self.query_instruction}{text}" if self.query_instruction else text
        return self._encode_batch([query])[0]

    def _encode_batch(self, batch: list[str]) -> list[list[float]]:
        attempts = self.max_retries + 1
        last_error = "unknown"

        for attempt in range(attempts):
            try:
                response = self._client.post(
                    self.endpoint,
                    json=self._payload(batch),
                    headers=self._headers(),
                    timeout=self.timeout,
                )
            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning("embedding request timed out attempt=%s", attempt + 1)
            except httpx.HTTPError:
                last_error = "network error"
                logger.warning("embedding request failed attempt=%s", attempt + 1)
            else:
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    last_error = f"status {response.status_code}"
                    logger.warning(
                        "embedding request failed with status=%s attempt=%s",
                        response.status_code,
                        attempt + 1,
                    )
                elif response.status_code >= 400:
                    raise EmbeddingUnavailable(
                        f"OpenRouter embeddings request failed with status {response.status_code}"
                    )
                else:
                    return self._parse_vectors(response, len(batch))

            if attempt < attempts - 1 and self.backoff_base > 0:
                time.sleep(self.backoff_base * (2**attempt))

        raise EmbeddingUnavailable(
            f"OpenRouter embeddings unavailable after {attempts} attempts: {last_error}"
        )

    def _parse_vectors(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            entries = sorted(
                response.json()["data"],
                key=lambda item: int(item.get("index", 0)),
            )
            vectors = [[float(value) for value in item["embedding"]] for item in entries]
        except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise EmbeddingUnavailable("OpenRouter returned an unexpected response") from exc

        if len(vectors) != expected:
            raise EmbeddingUnavailable(
                f"OpenRouter returned {len(vectors)} embeddings for {expected} inputs"
            )
        for vector in vectors:
            if len(vector) != self.dimension:
                raise ValueError(
                    "embedding dimension mismatch: OPENROUTER_EMBEDDING_DIMENSIONS expects "
                    f"{self.dimension}, got {len(vector)}"
                )
        return vectors


def _pplx_field_for(model_path: str) -> str:
    return "ppx_9b_model_path" if "9b" in model_path.lower() else "ppx_06b_model_path"


def _require_revision(revision: str | None) -> str:
    value = (revision or "").strip()
    if not value or value.lower() == "main":
        raise ValueError(
            "embedding model revision must be pinned to a commit/tag other than 'main'; "
            f"got {revision!r}. Set EMBEDDING_MODEL_REVISION in Settings/config."
        )
    return value


def _reject_gguf(field: str, path: str) -> None:
    if path and path.lower().endswith(".gguf"):
        raise ModelFormatError(
            f"{field}={path!r} is a GGUF (llama.cpp) artifact; "
            "sentence-transformers cannot load it. "
            "Point the setting at a safetensors model directory or use the fallback path. "
            f"Local GGUF artifacts: {LOCAL_06B_GGUF} and {LOCAL_9B_GGUF}."
        )


def _load_sentence_transformer(model_name: str, revision: str) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, revision=revision)


def get_encoder(settings: Any) -> Encoder:
    provider = settings.embedding_provider

    if provider == "openrouter":
        return OpenRouterEncoder(
            str(getattr(settings, "openrouter_embedding_model", "") or OPENROUTER_DEFAULT_MODEL),
            api_key=str(getattr(settings, "openrouter_api_key", "") or ""),
            base_url=str(
                getattr(settings, "openrouter_base_url", "") or OPENROUTER_DEFAULT_BASE_URL
            ),
            dimension=int(getattr(settings, "openrouter_embedding_dimensions", DEFAULT_DIMENSION)),
            batch_size=int(getattr(settings, "openrouter_batch_size", 32)),
            timeout=float(getattr(settings, "openrouter_timeout", 60.0)),
            max_retries=int(getattr(settings, "openrouter_max_retries", 2)),
            data_collection=getattr(settings, "openrouter_data_collection", "deny"),
            zdr=bool(getattr(settings, "openrouter_zdr", True)),
            site_url=str(getattr(settings, "openrouter_site_url", "") or ""),
            app_name=str(getattr(settings, "openrouter_app_name", "") or ""),
            query_instruction=str(getattr(settings, "openrouter_query_instruction", "") or ""),
        )

    revision = _revision(settings)

    if provider == "harrier":
        return HarrierEncoder(
            getattr(settings, "harrier_model_path", "") or DEFAULT_HARRIER_MODEL,
            revision=revision,
        )

    if provider == "pplx":
        if settings.retrieval_path == "target":
            field_name = "ppx_9b_model_path"
            path = getattr(settings, field_name, "") or DEFAULT_PPLX_9B_MODEL
        else:
            field_name = "ppx_06b_model_path"
            path = getattr(settings, field_name, "") or DEFAULT_PPLX_06B_MODEL
        return PPLXEncoder(path, revision=revision, settings_field=field_name)

    raise ValueError(f"unsupported embedding_provider={provider!r}")


def _revision(settings: Any) -> str:
    return getattr(settings, "embedding_model_revision", "") or getattr(
        settings, "model_revision", ""
    )


def embedding_text_hash(contexto: str, texto_literal: str) -> str:
    return hashlib.sha256((contexto + "\n" + texto_literal).encode("utf-8")).hexdigest()


def embed_chunks(
    chunks: Iterable[Chunk],
    encoder: Encoder,
    batch_size: int = 32,
) -> list[EmbeddedChunk]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    items = list(chunks)
    embedded: list[EmbeddedChunk] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        vectors = encoder.encode_documents([chunk.texto_indexacao for chunk in batch])
        if len(vectors) != len(batch):
            raise ValueError(f"encoder returned {len(vectors)} vectors for {len(batch)} chunks")
        for chunk, vector in zip(batch, vectors, strict=True):
            embedded.append(
                EmbeddedChunk(
                    chunk=chunk,
                    embedding=[float(value) for value in vector],
                    model=encoder.model_name,
                    revision=encoder.revision,
                    text_hash=embedding_text_hash(chunk.contexto, chunk.texto_literal),
                )
            )
    return embedded
