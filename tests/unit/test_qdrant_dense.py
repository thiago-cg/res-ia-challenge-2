from __future__ import annotations

from types import SimpleNamespace

from src.index.embed import EmbeddedChunk, embedding_text_hash
from src.index.qdrant import (
    DENSE_VECTOR,
    QdrantDenseSearcher,
    ensure_dense_collection,
    query_dense,
    upsert_dense_chunks,
)
from src.index.run import _chunk_from_version
from tests.fixtures.chunk_seed import make_version


class FakeQdrant:
    def __init__(self) -> None:
        self.created = None
        self.points = []
        self.query = None
        self.exists = False

    def collection_exists(self, name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs):
        self.created = kwargs
        self.exists = True

    def create_payload_index(self, **kwargs) -> None:
        return None

    def upsert(self, **kwargs) -> None:
        self.points.extend(kwargs["points"])

    def query_points(self, **kwargs):
        self.query = kwargs
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id="point-1",
                    score=0.9,
                    payload={
                        "device_id": "lmp/art22/cpt/inc3/ali-b",
                        "norm_version_id": 1,
                        "vigencia_status": "vigente",
                    },
                )
            ]
        )


class FixedEncoder:
    dimension = 4
    model_name = "fixed"
    revision = "fixed"

    def encode_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


def _embedded() -> EmbeddedChunk:
    chunk = _chunk_from_version(make_version("lmp/art22/cpt/inc3/ali-b", "texto literal"))
    return EmbeddedChunk(
        chunk=chunk,
        embedding=[0.1, 0.2, 0.3, 0.4],
        model="qwen/qwen3-embedding-8b",
        revision="openrouter:qwen/qwen3-embedding-8b",
        text_hash=embedding_text_hash(chunk.contexto, chunk.texto_literal),
    )


def test_dense_collection_uses_4096_float16_cosine() -> None:
    client = FakeQdrant()

    name = ensure_dense_collection(client, size=4096, alias_name=None)

    assert name
    assert client.created["vectors_config"][DENSE_VECTOR].size == 4096
    assert client.created["vectors_config"][DENSE_VECTOR].datatype.value == "float16"


def test_upsert_dense_payload_has_no_legal_text() -> None:
    client = FakeQdrant()
    item = _embedded()

    indexed = upsert_dense_chunks(client, [item], collection_name="dense")

    assert indexed == 1
    point = client.points[0]
    assert point.vector[DENSE_VECTOR] == [0.1, 0.2, 0.3, 0.4]
    assert point.payload["device_id"] == "lmp/art22/cpt/inc3/ali-b"
    assert "texto_literal" not in point.payload
    assert point.payload["embedding_model"] == "qwen/qwen3-embedding-8b"


def test_query_dense_uses_named_vector_and_vigencia_filter() -> None:
    client = FakeQdrant()

    hits = query_dense(client, [0.1] * 4096, limit=7)

    assert client.query["using"] == DENSE_VECTOR
    assert client.query["limit"] == 7
    assert client.query["query_filter"] is not None
    assert hits[0].device_id == "lmp/art22/cpt/inc3/ali-b"
    assert hits[0].source == "dense"


def test_dense_searcher_encodes_query_and_returns_dense_source() -> None:
    client = FakeQdrant()
    searcher = QdrantDenseSearcher("http://unused", FixedEncoder(), client=client)

    hits = searcher.search("pergunta", limit=3)

    assert hits[0].source == "dense"
    assert client.query["query"] == [1.0, 0.0, 0.0, 0.0]
