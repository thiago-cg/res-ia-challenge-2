from __future__ import annotations

import hashlib
import math
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.config import LOCAL_06B_GGUF, LOCAL_9B_GGUF, Settings
from src.contracts import ModelFormatError
from src.index.chunk import build_chunks
from src.index.embed import (
    HARRIER_INSTRUCTION,
    EmbeddedChunk,
    HarrierEncoder,
    MockEncoder,
    PPLXEncoder,
    embed_chunks,
    embedding_text_hash,
    get_encoder,
)
from tests.fixtures.chunk_seed import (
    lmp_art22_devices,
    lmp_art22_versions,
    make_device,
    make_version,
)


class FakeSentenceTransformer:
    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def encode(self, texts, **kwargs):
        self.calls.append(list(texts))
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]


class RecordingEncoder(BaseModel):
    model_name: str = "recording"
    revision: str = "rev-1"
    dimension: int = 2

    def encode_documents(self, texts):
        recorded.append(list(texts))
        return [[float(index), 0.0] for index, _ in enumerate(texts)]

    def encode_query(self, text):
        return [0.0, 1.0]


recorded: list[list[str]] = []


def test_mock_encoder_is_deterministic_and_l2_normalized() -> None:
    encoder = MockEncoder(dimension=8)

    first = encoder.encode_documents(["texto a", "texto b"])
    second = encoder.encode_documents(["texto a", "texto b"])

    assert len(first) == 2
    assert all(len(vector) == 8 for vector in first)
    assert first == second
    assert first[0] != first[1]
    for vector in first:
        assert abs(math.sqrt(sum(value * value for value in vector)) - 1.0) < 1e-9
    assert encoder.encode_query("texto a") == first[0]


def test_get_encoder_selects_harrier_and_pplx_paths_by_retrieval_path() -> None:
    harrier = Settings(
        _env_file=None,
        embedding_provider="harrier",
        harrier_model_path="/models/harrier",
        embedding_model_revision="rev-harrier",
    )
    harrier_encoder = get_encoder(harrier)
    assert harrier_encoder.model_name == "/models/harrier"
    assert harrier_encoder.revision == "rev-harrier"

    target = Settings(
        _env_file=None,
        embedding_provider="pplx",
        retrieval_path="target",
        ppx_9b_model_path="/models/pplx-9b",
        ppx_06b_model_path="/models/pplx-06b",
        embedding_model_revision="rev-9b",
    )
    encoder = get_encoder(target)
    assert isinstance(encoder, PPLXEncoder)
    assert encoder.model_name == "/models/pplx-9b"

    fallback = Settings(
        _env_file=None,
        embedding_provider="pplx",
        retrieval_path="fallback",
        ppx_9b_model_path="/models/pplx-9b",
        ppx_06b_model_path="/models/pplx-06b",
        embedding_model_revision="rev-06b",
    )
    assert get_encoder(fallback).model_name == "/models/pplx-06b"


def test_get_encoder_rejects_mock_provider() -> None:
    fake = SimpleNamespace(embedding_provider="mock", retrieval_path="fallback")
    with pytest.raises(ValueError, match="unsupported embedding_provider"):
        get_encoder(fake)


def test_get_encoder_requires_pinned_revision() -> None:
    settings = Settings(
        _env_file=None,
        embedding_provider="harrier",
        harrier_model_path="/models/harrier",
    )
    with pytest.raises(ValueError, match="revision must be pinned"):
        get_encoder(settings)


def test_get_encoder_gguf_uses_matching_config_field_name() -> None:
    fake = SimpleNamespace(
        embedding_provider="pplx",
        retrieval_path="target",
        ppx_9b_model_path="/models/pplx-9b.gguf",
        ppx_06b_model_path="",
        embedding_model_revision="rev-9b",
    )
    with pytest.raises(ModelFormatError) as excinfo:
        get_encoder(fake)

    assert "ppx_9b_model_path" in str(excinfo.value)


@pytest.mark.parametrize("encoder_class", [HarrierEncoder, PPLXEncoder])
def test_gguf_paths_are_rejected_with_actionable_message(encoder_class) -> None:
    with pytest.raises(ModelFormatError) as excinfo:
        encoder_class(r"C:\models\embed-v2-Q8_0.gguf")

    message = str(excinfo.value)
    assert ".gguf" in message
    assert "safetensors" in message
    assert "fallback" in message
    assert LOCAL_9B_GGUF in message
    assert LOCAL_06B_GGUF in message


def test_revision_is_recorded() -> None:
    assert HarrierEncoder("/models/harrier", revision="abc123").revision == "abc123"
    assert PPLXEncoder("/models/pplx", revision="def456").revision == "def456"


@pytest.mark.parametrize("encoder_class", [HarrierEncoder, PPLXEncoder])
@pytest.mark.parametrize("revision", [None, "", "  ", "main", "MAIN"])
def test_encoders_reject_unpinned_revisions(encoder_class, revision) -> None:
    with pytest.raises(ValueError, match="revision must be pinned"):
        encoder_class("/models/embed", revision=revision)


def test_harrier_puts_instruction_on_query_only() -> None:
    fake = FakeSentenceTransformer(dimension=4)
    encoder = HarrierEncoder("/models/harrier", revision="rev-1", model=fake, dimension=4)

    encoder.encode_documents(["documento literal"])
    encoder.encode_query("pergunta da vítima")

    assert fake.calls[0] == ["documento literal"]
    assert fake.calls[1] == [HARRIER_INSTRUCTION + "pergunta da vítima"]


def test_pplx_does_not_add_harrier_instruction() -> None:
    fake = FakeSentenceTransformer(dimension=4)
    encoder = PPLXEncoder("/models/pplx", revision="rev-1", model=fake, dimension=4)

    encoder.encode_documents(["documento"])
    encoder.encode_query("pergunta")

    assert fake.calls[0] == ["documento"]
    assert fake.calls[1] == ["pergunta"]


def test_embedding_text_hash_is_stable_and_separator_sensitive() -> None:
    expected = hashlib.sha256(b"contexto\ntexto").hexdigest()

    assert embedding_text_hash("contexto", "texto") == expected
    assert embedding_text_hash("contexto", "texto") == embedding_text_hash("contexto", "texto")
    assert embedding_text_hash("contexto", "texto") != embedding_text_hash("contexto", "outro")
    assert embedding_text_hash("contexto", "texto") != embedding_text_hash("outro", "texto")


def test_embed_chunks_batches_and_never_mutates_literal_text() -> None:
    recorded.clear()
    devices = lmp_art22_devices()
    versions = lmp_art22_versions()
    devices.append(
        make_device(
            "lmp/art22/cpt/inc4",
            parent_id="lmp/art22/cpt",
            tipo="inciso",
            rotulo="inciso IV",
            artigo_id="lmp/art22",
        )
    )
    versions.append(make_version("lmp/art22/cpt/inc4", "medida de afastamento do lar;"))
    chunks = build_chunks(devices, versions)
    original_literals = [chunk.texto_literal for chunk in chunks]

    embedded = embed_chunks(chunks, RecordingEncoder(), batch_size=2)

    assert len(embedded) == len(chunks)
    assert [len(batch) for batch in recorded] == [2, 2, 1]
    assert [chunk.texto_literal for chunk in chunks] == original_literals
    assert all(isinstance(item, EmbeddedChunk) for item in embedded)
    assert all(item.model == "recording" and item.revision == "rev-1" for item in embedded)
    assert all(
        item.text_hash == embedding_text_hash(item.chunk.contexto, item.chunk.texto_literal)
        for item in embedded
    )
    assert embedded[0].device_id == chunks[0].device_id


def test_embed_chunks_rejects_empty_batch_size() -> None:
    chunks = build_chunks(lmp_art22_devices(), lmp_art22_versions())

    with pytest.raises(ValueError):
        embed_chunks(chunks, MockEncoder(), batch_size=0)


def test_embed_chunks_handles_empty_input() -> None:
    assert embed_chunks([], MockEncoder()) == []


def test_chunk_for_embedding_keeps_article_context_and_leaves() -> None:
    devices = lmp_art22_devices()
    devices.append(
        make_device(
            "lmp/art22/cpt/inc4",
            parent_id="lmp/art22/cpt",
            tipo="inciso",
            rotulo="inciso IV",
            artigo_id="lmp/art22",
        )
    )
    versions = lmp_art22_versions()
    versions.append(make_version("lmp/art22/cpt/inc4", "medida de afastamento do lar;"))

    chunks = build_chunks(devices, versions)
    embedded = embed_chunks(chunks, MockEncoder(dimension=4))

    assert len(embedded) == len(chunks)
    assert any(item.chunk.device_id == "lmp/art22" for item in embedded)
