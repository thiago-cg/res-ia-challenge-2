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
import math
from typing import Any, Protocol

from pydantic import BaseModel

from src.config import LOCAL_06B_GGUF, LOCAL_9B_GGUF
from src.contracts import ModelFormatError
from src.index.chunk import Chunk

DEFAULT_HARRIER_MODEL = "microsoft/harrier-oss-v1-0.6b"
DEFAULT_PPLX_06B_MODEL = "perplexity-ai/pplx-embed-v2-late-0.6b"
DEFAULT_PPLX_9B_MODEL = "perplexity-ai/pplx-embed-v2-late-9b"
DEFAULT_REVISION = "main"
DEFAULT_DIMENSION = 1024

HARRIER_INSTRUCTION = (
    "Instruct: Dada uma pergunta de uma vítima de violência doméstica, "
    "recupere o dispositivo legal que a responde.\nQuery: "
)
QUERY_INSTRUCTION = HARRIER_INSTRUCTION


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
        self.revision = revision or DEFAULT_REVISION
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
    ) -> None:
        _reject_gguf("ppx_model_path", model_path)
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
    revision = _revision(settings)

    if provider == "harrier":
        return HarrierEncoder(
            getattr(settings, "harrier_model_path", "") or DEFAULT_HARRIER_MODEL,
            revision=revision,
        )

    if provider == "pplx":
        if settings.retrieval_path == "target":
            path = getattr(settings, "ppx_9b_model_path", "") or DEFAULT_PPLX_9B_MODEL
        else:
            path = getattr(settings, "ppx_06b_model_path", "") or DEFAULT_PPLX_06B_MODEL
        return PPLXEncoder(path, revision=revision)

    if provider == "mock":
        return MockEncoder()

    raise ValueError(f"unsupported embedding_provider={provider!r}")


def _revision(settings: Any) -> str:
    return (
        getattr(settings, "embedding_model_revision", None)
        or getattr(settings, "model_revision", None)
        or DEFAULT_REVISION
    )


def embedding_text_hash(contexto: str, texto_literal: str) -> str:
    return hashlib.sha256((contexto + "\n" + texto_literal).encode("utf-8")).hexdigest()


def embed_chunks(
    chunks: list[Chunk],
    encoder: Encoder,
    batch_size: int = 32,
) -> list[EmbeddedChunk]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    embedded: list[EmbeddedChunk] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
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
