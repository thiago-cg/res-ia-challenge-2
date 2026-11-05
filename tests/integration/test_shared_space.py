"""Gate for the shared 9B index / 0.6B query vector space.

The smoke test needs a GPU, safetensors checkpoints and a live Qdrant.  When any
of those is missing it skips with an explicit reason instead of passing
silently.  GGUF artifacts are never accepted as a substitute: they must raise
``ModelFormatError``.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from src.contracts import ModelFormatError
from src.index.chunk import build_chunks
from src.index.embed import PPLXEncoder
from src.index.qdrant import (
    IndexedChunk,
    QueryVectors,
    ensure_collection,
    query_target,
    sparse_vector,
    upsert_chunks,
)
from tests.fixtures.chunk_seed import lmp_art22_devices, lmp_art22_versions


def test_gguf_artifacts_raise_model_format_error_instead_of_silently_passing() -> None:
    for path in ("pplx-embed-v2-late-9b.gguf", "pplx-embed-v2-late-0.6b.Q8_0.gguf"):
        with pytest.raises(ModelFormatError):
            PPLXEncoder(path)


def _require_cuda() -> None:
    try:
        import torch
    except ImportError:
        pytest.skip("torch is not installed; shared-space smoke needs a GPU")
    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU available for the 9B/0.6B shared-space smoke")


def _require_model(env_name: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        pytest.skip(f"{env_name} is not set; safetensors model missing")
    path = Path(raw)
    if path.suffix.lower() == ".gguf":
        raise ModelFormatError(
            f"{env_name}={raw!r} is GGUF; the shared-space smoke requires safetensors"
        )
    if not path.exists():
        pytest.skip(f"{env_name}={raw!r} does not exist; safetensors model missing")
    return path


def _require_qdrant():
    url = os.environ.get("TEST_QDRANT_URL")
    if not url:
        pytest.skip("Qdrant not configured; set TEST_QDRANT_URL")

    try:
        from qdrant_client import QdrantClient
    except ImportError:  # pragma: no cover - dependency is declared
        pytest.skip("qdrant-client is not installed")

    client = QdrantClient(url=url, timeout=5)
    try:
        client.get_collections()
    except Exception as exc:  # pragma: no cover - local service dependent
        pytest.skip(f"Qdrant not reachable at TEST_QDRANT_URL: {exc}")
    return client


def _multi_vector_encoder(path: Path, revision: str):
    try:
        from sentence_transformers import MultiVectorEncoder
    except ImportError:
        pytest.skip("sentence-transformers MultiVectorEncoder is not installed")

    return MultiVectorEncoder(str(path), revision=revision, device="cuda")


@pytest.mark.integration
@pytest.mark.slow
def test_index_with_9b_and_query_with_06b_hits_the_same_device() -> None:
    _require_cuda()
    index_model = _require_model("PPX_9B_MODEL_PATH")
    query_model = _require_model("PPX_06B_MODEL_PATH")
    revision = os.environ.get("EMBEDDING_MODEL_REVISION", "").strip()
    if not revision or revision.lower() == "main":
        pytest.skip("EMBEDDING_MODEL_REVISION must be pinned for the shared-space smoke")

    client = _require_qdrant()
    chunk = build_chunks(lmp_art22_devices(), lmp_art22_versions()).chunks[0]
    name = f"idx05_shared_{uuid.uuid4().hex[:10]}"

    index_encoder = _multi_vector_encoder(index_model, revision)
    query_encoder = _multi_vector_encoder(query_model, revision)

    try:
        ensure_collection(client, collection_name=name, alias_name=None)

        documents = index_encoder.encode_documents([chunk.texto_indexacao])
        doc_vectors = _matrix(documents[0])
        upsert_chunks(
            client,
            [
                IndexedChunk(
                    chunk=chunk,
                    late_vectors=doc_vectors,
                    bm25=sparse_vector(chunk.search_text),
                )
            ],
            collection_name=name,
        )

        queries = query_encoder.encode_query([chunk.citacao])
        query_vectors = _matrix(queries[0])
        hits = query_target(
            client,
            QueryVectors(
                bm25=sparse_vector(chunk.search_text),
                late=query_vectors,
            ),
            collection_name=name,
        )

        assert hits, "shared-space smoke returned no candidates"
        assert hits[0].device_id == chunk.device_id
    finally:
        client.delete_collection(name)


def _matrix(value) -> list[list[float]]:
    first = value[0]
    if isinstance(first, (int, float)):
        return [[float(item) for item in value]]
    return [[float(item) for item in row] for row in value]
