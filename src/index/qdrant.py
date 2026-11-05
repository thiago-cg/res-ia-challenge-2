"""Qdrant multivector index for the target retrieval path.

The collection contract is fixed by docs/05 §3: a ``late`` multivector named
vector (128 dimensions, Cosine, ``max_sim``, float16), a sparse ``bm25`` named
vector with server-side IDF, and a payload that never carries legal text.  Text
hydration happens in Postgres by ``(device_id, norm_version_id)``.

Imports from ``qdrant_client`` are lazy so the module can be imported (and unit
tested with a fake client) without the service or the package present at import
time.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from src.contracts import RetrievedDevice
from src.index.chunk import Chunk

if TYPE_CHECKING:  # pragma: no cover - typing only
    from qdrant_client import QdrantClient, models

COLLECTION_NAME = "devices_qdrant_current"
ALIAS_NAME = COLLECTION_NAME
COLLECTION_ALIAS = COLLECTION_NAME
COLLECTION_PHYSICAL_NAME = "devices_qdrant_v1"
PHYSICAL_COLLECTION_NAME = COLLECTION_PHYSICAL_NAME

LATE_VECTOR = "late"
BM25_VECTOR = "bm25"
LATE_SIZE = 128

PREFETCH_LIMIT = 100
MAX_RESCORE = 150
RESULT_LIMIT = 10
UPSERT_BATCH_SIZE = 64

PAYLOAD_FIELDS = (
    "device_id",
    "norm_version_id",
    "norm_id",
    "artigo_id",
    "tipo",
    "vigencia_status",
    "vigencia_inicio",
    "vigencia_fim",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass
class IndexedChunk:
    """A chunk together with the vectors that go to Qdrant.

    ``late_vectors`` is the token matrix produced by the 9B document encoder.
    ``bm25`` is derived from ``chunk.search_text`` when omitted.
    """

    chunk: Chunk
    late_vectors: list[list[float]]
    bm25: Any | None = None

    @property
    def late(self) -> list[list[float]]:
        return self.late_vectors


@dataclass
class QueryVectors:
    """Query-side vectors: sparse BM25 query and the 0.6B late matrix."""

    bm25: Any
    late: list[list[float]]


def point_id(device_id: str, norm_version_id: int) -> UUID:
    """Deterministic point id: ``UUIDv5(NAMESPACE_URL, f"{device_id}@{id}")``."""

    return uuid5(NAMESPACE_URL, f"{device_id}@{norm_version_id}")


point_id_for = point_id


def sparse_vector(text: str) -> models.SparseVector:
    """Build a deterministic BM25 sparse vector from normalized text.

    Values are term frequencies; Qdrant applies the IDF modifier server-side.
    Indices are stable 32-bit hashes of each normalized token.
    """

    from qdrant_client import models

    tokens = _tokenize(text)
    if not tokens:
        return models.SparseVector(indices=[], values=[])

    counts = Counter(tokens)
    pairs = sorted((_token_index(token), float(count)) for token, count in counts.items())
    return models.SparseVector(
        indices=[index for index, _ in pairs],
        values=[value for _, value in pairs],
    )


def ensure_collection(
    client: QdrantClient,
    *,
    collection_name: str = COLLECTION_PHYSICAL_NAME,
    alias_name: str | None = ALIAS_NAME,
) -> str:
    """Create the collection if needed and point the alias at it.

    Returns the name queries should use (the alias when one is configured).
    """

    from qdrant_client import models

    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                LATE_VECTOR: models.VectorParams(
                    size=LATE_SIZE,
                    distance=models.Distance.COSINE,
                    datatype=models.Datatype.FLOAT16,
                    multivector_config=models.MultiVectorConfig(
                        comparator=models.MultiVectorComparator.MAX_SIM
                    ),
                )
            },
            sparse_vectors_config={
                BM25_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

    if alias_name:
        _ensure_alias(client, collection_name, alias_name)
        return alias_name
    return collection_name


def upsert_chunks(
    client: QdrantClient,
    chunks: Iterable[Chunk | IndexedChunk | Any],
    *,
    collection_name: str = COLLECTION_ALIAS,
    batch_size: int = UPSERT_BATCH_SIZE,
) -> int:
    """Upsert one point per ``(device_id, norm_version_id)``.

    Accepts :class:`IndexedChunk`, :class:`~src.index.embed.EmbeddedChunk` or
    any object exposing ``late_vectors``/``late``; an ``EmbeddedChunk``'s dense
    embedding becomes a single-subvector multivector.
    """

    from qdrant_client import models

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    points = [_point(models, item) for item in chunks]
    for start in range(0, len(points), batch_size):
        client.upsert(
            collection_name=collection_name,
            points=points[start : start + batch_size],
            wait=True,
        )
    return len(points)


def query_target(
    client: QdrantClient,
    query_vectors: QueryVectors | Any,
    *,
    top_k: int = PREFETCH_LIMIT,
    data_fato: date | None = None,
    collection_name: str = COLLECTION_ALIAS,
    limit: int = RESULT_LIMIT,
) -> list[RetrievedDevice]:
    """Hybrid query: BM25 prefetch, then late MaxSim rescore, top ``limit``.

    Payload text is intentionally absent; callers hydrate
    ``texto_literal``/``citacao`` from Postgres by ``(device_id, norm_version_id)``.
    """

    from qdrant_client import models

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")

    top_k = min(top_k, MAX_RESCORE)
    limit = min(limit, MAX_RESCORE)

    vectors = _coerce_query_vectors(query_vectors)
    vigencia = _vigencia_filter(models, data_fato)

    response = client.query_points(
        collection_name=collection_name,
        prefetch=[
            models.Prefetch(
                query=vectors.bm25,
                using=BM25_VECTOR,
                limit=top_k,
                filter=vigencia,
            )
        ],
        query=vectors.late,
        using=LATE_VECTOR,
        query_filter=vigencia,
        limit=limit,
        with_payload=True,
    )
    return [_retrieved(point) for point in getattr(response, "points", response)]


def _ensure_alias(client: QdrantClient, collection_name: str, alias_name: str) -> None:
    from qdrant_client import models

    if not hasattr(client, "get_aliases") or not hasattr(client, "update_collection_aliases"):
        return

    aliases = getattr(client.get_aliases(), "aliases", []) or []
    current = {alias.alias_name: alias.collection_name for alias in aliases}
    if current.get(alias_name) == collection_name:
        return

    operations: list[Any] = [
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(
                collection_name=collection_name,
                alias_name=alias_name,
            )
        )
    ]
    if alias_name in current:
        operations.insert(
            0,
            models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias_name)),
        )
    client.update_collection_aliases(change_aliases_operations=operations)


def _point(models: Any, item: Any) -> Any:
    chunk, late_vectors, bm25 = _normalize_indexed(item)
    return models.PointStruct(
        id=str(point_id(chunk.device_id, chunk.norm_version_id)),
        vector={
            LATE_VECTOR: late_vectors,
            BM25_VECTOR: bm25,
        },
        payload=payload_for(chunk),
    )


def _normalize_indexed(
    item: Chunk | IndexedChunk | Any,
) -> tuple[Chunk, list[list[float]], Any]:
    from qdrant_client import models

    chunk = getattr(item, "chunk", item)
    if not isinstance(chunk, Chunk):
        raise TypeError(f"expected a Chunk or an object with .chunk, got {type(item)!r}")

    late = getattr(item, "late_vectors", None)
    if late is None:
        late = getattr(item, "late", None)
    if late is None:
        embedding = getattr(item, "embedding", None)
        if embedding is not None:
            late = [embedding]
    if late is None:
        raise ValueError(
            f"chunk {chunk.device_id!r} has no late vectors; pass IndexedChunk or EmbeddedChunk"
        )

    bm25 = getattr(item, "bm25", None)
    if bm25 is None:
        bm25 = sparse_vector(chunk.search_text)
    elif not isinstance(bm25, models.SparseVector):
        bm25 = _coerce_sparse(bm25)
    return chunk, _as_matrix(late), bm25


def _coerce_query_vectors(query_vectors: QueryVectors | Any) -> QueryVectors:
    bm25: Any
    late: Any
    if isinstance(query_vectors, QueryVectors):
        bm25, late = query_vectors.bm25, query_vectors.late
    elif isinstance(query_vectors, dict):
        bm25 = query_vectors.get("bm25", query_vectors.get("sparse"))
        late = query_vectors.get("late", query_vectors.get("dense"))
    else:
        bm25 = getattr(query_vectors, "bm25", getattr(query_vectors, "sparse", None))
        late = getattr(query_vectors, "late", getattr(query_vectors, "dense", None))
    if bm25 is None or late is None:
        raise TypeError("query_vectors must expose bm25 and late")
    return QueryVectors(bm25=_coerce_sparse(bm25), late=_as_matrix(late))


def _coerce_sparse(value: Any) -> Any:
    from qdrant_client import models

    if isinstance(value, models.SparseVector):
        return value
    if isinstance(value, dict):
        return models.SparseVector(**value)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return models.SparseVector(indices=list(value[0]), values=list(value[1]))
    raise TypeError(f"cannot coerce {type(value)!r} into a SparseVector")


def _as_matrix(value: Any) -> list[list[float]]:
    if not value:
        return []
    first = value[0]
    if isinstance(first, (int, float)) or not hasattr(first, "__len__"):
        return [[float(item) for item in value]]
    return [[float(item) for item in row] for row in value]


def _vigencia_filter(models: Any, data_fato: date | None) -> Any:
    if data_fato is None:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="vigencia_status",
                    match=models.MatchAny(any=["vigente", "alterado"]),
                )
            ]
        )

    return models.Filter(
        must=[
            models.FieldCondition(
                key="vigencia_inicio",
                range=models.DatetimeRange(lte=data_fato),
            ),
            models.Filter(
                should=[
                    models.FieldCondition(
                        key="vigencia_fim",
                        range=models.DatetimeRange(gte=data_fato),
                    ),
                    models.IsNullCondition(is_null=models.PayloadField(key="vigencia_fim")),
                ]
            ),
        ]
    )


def payload_for(chunk: Chunk) -> dict[str, Any]:
    return {
        "device_id": chunk.device_id,
        "norm_version_id": chunk.norm_version_id,
        "norm_id": chunk.norm_id,
        "artigo_id": chunk.artigo_id,
        "tipo": chunk.tipo,
        "vigencia_status": chunk.vigencia_status,
        "vigencia_inicio": chunk.vigencia_inicio.isoformat(),
        "vigencia_fim": (
            chunk.vigencia_fim.isoformat() if chunk.vigencia_fim is not None else None
        ),
    }


def _retrieved(point: Any) -> RetrievedDevice:
    payload = dict(getattr(point, "payload", None) or {})
    missing = [
        field
        for field in ("device_id", "norm_version_id", "vigencia_status")
        if payload.get(field) in (None, "")
    ]
    if missing:
        raise ValueError(f"Qdrant point {getattr(point, 'id', '?')} missing payload: {missing}")

    return RetrievedDevice(
        device_id=str(payload["device_id"]),
        norm_version_id=int(payload["norm_version_id"]),
        score=float(getattr(point, "score", 0.0)),
        source="maxsim",
        texto_literal="",
        citacao="",
        vigencia=payload["vigencia_status"],
    )


def _tokenize(text: str) -> list[str]:
    stripped = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in stripped if not unicodedata.combining(char))
    return _TOKEN_RE.findall(without_accents.lower())


def _token_index(token: str) -> int:
    import hashlib

    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big")
