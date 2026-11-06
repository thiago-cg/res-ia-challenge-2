from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from qdrant_client import models

from src.index.chunk import build_chunks
from src.index.embed import EmbeddedChunk
from src.index.qdrant import (
    ALIAS_NAME,
    BM25_VECTOR,
    COLLECTION_PHYSICAL_NAME,
    LATE_VECTOR,
    IndexedChunk,
    QueryVectors,
    ensure_collection,
    payload_for,
    point_id,
    query_target,
    sparse_vector,
    upsert_chunks,
)
from tests.fixtures.chunk_seed import lmp_art22_devices, lmp_art22_versions


class FakeClient:
    def __init__(self, *, exists: bool = False, points: list | None = None) -> None:
        self.exists = exists
        self.collections: set[str] = {COLLECTION_PHYSICAL_NAME} if exists else set()
        self.created: dict | None = None
        self.aliases: list[SimpleNamespace] = []
        self.upserts: list[dict] = []
        self.query: dict | None = None
        self.response_points = points or []

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def create_collection(self, **kwargs) -> None:
        self.created = kwargs
        self.collections.add(kwargs["collection_name"])

    def get_aliases(self):
        return SimpleNamespace(aliases=self.aliases)

    def update_collection_aliases(self, change_aliases_operations):
        for operation in change_aliases_operations:
            create = getattr(operation, "create_alias", None)
            if create is not None:
                self.aliases = [
                    alias for alias in self.aliases if alias.alias_name != create.alias_name
                ]
                self.aliases.append(
                    SimpleNamespace(
                        alias_name=create.alias_name,
                        collection_name=create.collection_name,
                    )
                )
            delete = getattr(operation, "delete_alias", None)
            if delete is not None:
                alias = delete.alias_name
                self.aliases = [item for item in self.aliases if item.alias_name != alias]

    def upsert(self, collection_name, points, wait=True):
        self.upserts.append(
            {"collection_name": collection_name, "points": list(points), "wait": wait}
        )

    def query_points(self, **kwargs):
        self.query = kwargs
        return SimpleNamespace(points=self.response_points)


def chunks():
    return build_chunks(lmp_art22_devices(), lmp_art22_versions()).chunks


def late_matrix():
    return [[0.1] * 128, [0.2] * 128]


def test_ensure_collection_sets_multivector_sparse_contract_and_alias() -> None:
    client = FakeClient()

    target = ensure_collection(client)

    assert target == ALIAS_NAME
    assert client.created is not None
    late = client.created["vectors_config"][LATE_VECTOR]
    assert late.size == 128
    assert late.distance == models.Distance.COSINE
    assert late.datatype == models.Datatype.FLOAT16
    assert late.multivector_config.comparator == models.MultiVectorComparator.MAX_SIM
    bm25 = client.created["sparse_vectors_config"][BM25_VECTOR]
    assert bm25.modifier == models.Modifier.IDF
    assert any(
        alias.alias_name == ALIAS_NAME and alias.collection_name == COLLECTION_PHYSICAL_NAME
        for alias in client.aliases
    )


def test_ensure_collection_is_idempotent_and_keeps_alias() -> None:
    client = FakeClient(exists=True)

    ensure_collection(client)

    assert client.created is None
    assert client.aliases[0].alias_name == ALIAS_NAME


def test_point_id_is_uuid5_of_device_at_version() -> None:
    expected = uuid5(NAMESPACE_URL, "lmp/art22@42")

    assert point_id("lmp/art22", 42) == expected
    assert point_id("lmp/art22", 42) == point_id("lmp/art22", 42)
    assert point_id("lmp/art22", 43) != expected


def test_upsert_uses_uuid5_payload_without_text() -> None:
    client = FakeClient()
    chunk = chunks()[0]

    count = upsert_chunks(
        client,
        [IndexedChunk(chunk=chunk, late_vectors=late_matrix())],
        collection_name=ALIAS_NAME,
    )

    assert count == 1
    point = client.upserts[0]["points"][0]
    assert point.id == str(uuid5(NAMESPACE_URL, f"{chunk.device_id}@{chunk.norm_version_id}"))
    assert set(point.vector) == {LATE_VECTOR, BM25_VECTOR}
    assert len(point.vector[LATE_VECTOR]) == 2
    assert point.vector[BM25_VECTOR].indices
    assert point.payload == {
        "device_id": chunk.device_id,
        "norm_version_id": chunk.norm_version_id,
        "norm_id": chunk.norm_id,
        "artigo_id": chunk.artigo_id,
        "tipo": chunk.tipo,
        "vigencia_status": chunk.vigencia_status,
        "vigencia_inicio": chunk.vigencia_inicio.isoformat(),
        "vigencia_fim": None,
    }
    serialized = repr(point.payload)
    assert chunk.texto_literal not in serialized
    assert chunk.contexto not in serialized


def test_payload_for_includes_required_fields_and_closes_dates() -> None:
    chunk = chunks()[1].model_copy(update={"vigencia_fim": date(2010, 1, 2)})

    payload = payload_for(chunk)

    assert payload["vigencia_inicio"] == chunk.vigencia_inicio.isoformat()
    assert payload["vigencia_fim"] == "2010-01-02"


def test_upsert_wraps_embedded_dense_vector_as_single_subvector() -> None:
    client = FakeClient()
    chunk = chunks()[0]
    embedded = EmbeddedChunk(
        chunk=chunk,
        embedding=[0.5] * 128,
        model="harrier",
        revision="rev",
        text_hash="hash",
    )

    upsert_chunks(client, [embedded], collection_name=ALIAS_NAME)

    point = client.upserts[0]["points"][0]
    assert point.id == str(uuid5(NAMESPACE_URL, f"{chunk.device_id}@{chunk.norm_version_id}"))
    assert len(point.vector[LATE_VECTOR]) == 1
    assert len(point.vector[LATE_VECTOR][0]) == 128


def test_sparse_vector_is_normalized_stable_and_counts_terms() -> None:
    first = sparse_vector("Medida protetiva, medida de proteção")
    second = sparse_vector("medida protetiva medida de protecao")

    assert first.indices == second.indices
    assert first.values == second.values
    highest = max(first.values)
    assert highest == 2.0


def test_query_target_uses_bm25_prefetch_then_late_rescore() -> None:
    chunk = chunks()[0]
    client = FakeClient(
        points=[
            SimpleNamespace(
                id="ignored",
                score=0.91,
                payload=payload_for(chunk),
            )
        ]
    )

    hits = query_target(
        client,
        QueryVectors(bm25=sparse_vector("medida protetiva"), late=late_matrix()),
        top_k=100,
    )

    query = client.query
    assert query is not None
    prefetch = query["prefetch"][0]
    assert prefetch.using == BM25_VECTOR
    assert prefetch.limit == 100
    assert query["using"] == LATE_VECTOR
    assert query["query"] == late_matrix()
    assert query["limit"] == 10
    assert query["with_payload"] is True
    must = query["query_filter"].must
    status_filter = must[0]
    assert status_filter.key == "vigencia_status"
    assert status_filter.match.any == ["vigente", "alterado"]
    assert must[1].key == "vigencia_inicio"
    assert must[1].range.lte == date.today()
    assert must[2].should[0].key == "vigencia_fim"
    assert must[2].should[0].range.gte == date.today()
    assert must[2].should[1].is_null.key == "vigencia_fim"
    assert len(hits) == 1
    assert hits[0].device_id == chunk.device_id
    assert hits[0].norm_version_id == chunk.norm_version_id
    assert hits[0].source == "maxsim"
    assert hits[0].texto_literal == ""
    assert hits[0].citacao == ""
    assert hits[0].vigencia == chunk.vigencia_status


def test_query_target_with_data_fato_uses_date_range_and_null_end() -> None:
    client = FakeClient(points=[])

    query_target(
        client,
        QueryVectors(bm25=sparse_vector("contato"), late=late_matrix()),
        data_fato=date(2020, 6, 1),
    )

    must = client.query["query_filter"].must
    assert must[0].key == "vigencia_inicio"
    assert must[0].range.lte.year == 2020
    nested = must[1]
    assert nested.should[0].key == "vigencia_fim"
    assert nested.should[0].range.gte.year == 2020
    assert nested.should[1].is_null.key == "vigencia_fim"
    assert client.query["prefetch"][0].filter.must[0].key == "vigencia_inicio"


def test_query_target_caps_prefetch_and_result_at_max_rescore() -> None:
    client = FakeClient(points=[])

    query_target(
        client,
        QueryVectors(bm25=sparse_vector("x"), late=late_matrix()),
        top_k=500,
        limit=500,
    )

    assert client.query["prefetch"][0].limit == 150
    assert client.query["limit"] == 150


@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"limit": 0}])
def test_query_target_rejects_non_positive_limits(kwargs) -> None:
    with pytest.raises(ValueError):
        query_target(
            FakeClient(),
            QueryVectors(bm25=sparse_vector("x"), late=late_matrix()),
            **kwargs,
        )


def test_query_target_rejects_points_without_payload() -> None:
    client = FakeClient(points=[SimpleNamespace(id="p", score=1.0, payload={})])

    with pytest.raises(ValueError, match="missing payload"):
        query_target(
            client,
            QueryVectors(bm25=sparse_vector("x"), late=late_matrix()),
        )


def test_upsert_rejects_chunks_without_vectors() -> None:
    with pytest.raises(ValueError, match="no late vectors"):
        upsert_chunks(FakeClient(), [chunks()[0]])


def test_upsert_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError):
        upsert_chunks(FakeClient(), [], batch_size=0)
