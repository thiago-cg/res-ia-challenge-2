from __future__ import annotations

import os
import uuid

import pytest

from src.index.chunk import build_chunks
from src.index.qdrant import (
    IndexedChunk,
    QueryVectors,
    ensure_collection,
    query_target,
    sparse_vector,
    upsert_chunks,
)
from tests.fixtures.chunk_seed import lmp_art22_devices, lmp_art22_versions


def _client():
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
    except Exception as exc:  # pragma: no cover - depends on local service
        pytest.skip(f"Qdrant not reachable at TEST_QDRANT_URL: {exc}")
    return client


def _late(active: int) -> list[list[float]]:
    vector = [0.0] * 128
    vector[active] = 1.0
    return [vector, [0.5] * 128]


@pytest.mark.integration
def test_collection_upsert_and_maxsim_query_return_the_indexed_device() -> None:
    client = _client()
    name = f"idx03_{uuid.uuid4().hex[:10]}"
    chunks = build_chunks(lmp_art22_devices(), lmp_art22_versions()).chunks[:2]

    try:
        ensure_collection(client, collection_name=name, alias_name=None)
        upsert_chunks(
            client,
            [
                IndexedChunk(
                    chunk=chunks[0],
                    late_vectors=_late(0),
                    bm25=sparse_vector("medida protetiva afastamento do lar"),
                ),
                IndexedChunk(
                    chunk=chunks[1],
                    late_vectors=_late(1),
                    bm25=sparse_vector("medida protetiva contato ofendida"),
                ),
            ],
            collection_name=name,
        )

        hits = query_target(
            client,
            QueryVectors(
                bm25=sparse_vector("medida protetiva afastamento do lar"),
                late=_late(0),
            ),
            collection_name=name,
        )

        assert hits, "Qdrant returned no candidates"
        assert hits[0].device_id == chunks[0].device_id
        assert hits[0].norm_version_id == chunks[0].norm_version_id
        assert hits[0].source == "maxsim"
        assert hits[0].texto_literal == ""
    finally:
        client.delete_collection(name)


@pytest.mark.integration
def test_alias_points_to_the_created_collection() -> None:
    client = _client()
    name = f"idx03_alias_{uuid.uuid4().hex[:10]}"
    alias = f"idx03_alias_current_{uuid.uuid4().hex[:10]}"

    try:
        ensure_collection(client, collection_name=name, alias_name=alias)
        aliases = client.get_aliases().aliases
        assert any(item.alias_name == alias and item.collection_name == name for item in aliases)
    finally:
        from qdrant_client import models

        try:
            client.update_collection_aliases(
                change_aliases_operations=[
                    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
                ]
            )
        except Exception:
            pass
        client.delete_collection(name)
