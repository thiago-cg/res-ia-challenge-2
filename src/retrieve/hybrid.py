"""Hybrid retrieval: dense + FTS with RRF, or Qdrant BM25 on the target path.

The fallback path never mixes embedding spaces: each subquestion runs a dense
search and a lexical search, both capped at 50, and the two ranked lists are
fused with Reciprocal Rank Fusion (``k=60``).  The target path delegates the
lexical BM25 search to Qdrant (top 100 per subquestion); MaxSim rescoring is
RET-04's job.  Both paths keep candidates keyed by ``(device_id,
norm_version_id)`` so different versions of the same device are never merged.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from datetime import date
from typing import Any, Protocol

from src.contracts import QueryPlan, RetrievedDevice

DEFAULT_RRF_K = 60
PER_SEARCH_LIMIT = 50
TARGET_BM25_LIMIT = 100
DEFAULT_MAX_CANDIDATES = 150

PairKey = tuple[str, int]


class DenseSearcher(Protocol):
    def search(self, query: str, limit: int, data_fato: date | None = None) -> Sequence[Any]: ...


class FtsSearcher(Protocol):
    def search(self, query: str, limit: int, data_fato: date | None = None) -> Sequence[Any]: ...


class QdrantSearcher(Protocol):
    def search(
        self, subquestion: str, top_k: int, data_fato: date | None = None
    ) -> Sequence[Any]: ...


def rrf[Key: Hashable](
    rank_lists: Sequence[Sequence[Key]], k: int = DEFAULT_RRF_K
) -> list[tuple[Key, float]]:
    """Reciprocal Rank Fusion exactly as in docs/05 §6.

    Each list contributes ``1 / (k + position)`` with ``position`` starting at
    1.  Ties keep first-seen order because Python's sort is stable.
    """

    if k < 0:
        raise ValueError("k must be non-negative")

    scores: dict[Key, float] = {}
    for ranks in rank_lists:
        for position, key in enumerate(ranks, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def hybrid_search(
    plan: QueryPlan,
    *,
    dense: DenseSearcher | None = None,
    fts: FtsSearcher | None = None,
    qdrant: QdrantSearcher | None = None,
    path: str = "fallback",
    data_fato: date | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[RetrievedDevice]:
    """Search every subquestion and return at most ``max_candidates`` devices.

    An empty result is a normal outcome (the caller abstains); no exception is
    raised for "nothing found".
    """

    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")

    subquestions = list(plan.subperguntas) or [plan.consulta_juridica]
    if path == "target":
        best = _target_candidates(subquestions, qdrant, data_fato)
    elif path == "fallback":
        best = _fallback_candidates(subquestions, dense, fts, data_fato)
    else:
        raise ValueError(f"unknown retrieval path: {path!r}")

    ranked = sorted(best.values(), key=lambda item: item.score, reverse=True)
    return ranked[:max_candidates]


def _fallback_candidates(
    subquestions: Sequence[str],
    dense: DenseSearcher | None,
    fts: FtsSearcher | None,
    data_fato: date | None,
) -> dict[PairKey, RetrievedDevice]:
    if dense is None or fts is None:
        raise ValueError("fallback requires both dense and fts searchers")

    best: dict[PairKey, RetrievedDevice] = {}
    for subquestion in subquestions:
        dense_hits = [
            _as_retrieved(item) for item in dense.search(subquestion, PER_SEARCH_LIMIT, data_fato)
        ]
        fts_hits = [
            _as_retrieved(item) for item in fts.search(subquestion, PER_SEARCH_LIMIT, data_fato)
        ]

        by_key = _by_pair(dense_hits + fts_hits)
        fts_keys = {_key(item) for item in fts_hits}
        fused = rrf(
            [[_key(item) for item in dense_hits], [_key(item) for item in fts_hits]],
            k=DEFAULT_RRF_K,
        )

        for key, score in fused:
            source_item = by_key[key]
            source = "bm25" if key in fts_keys else "dense"
            candidate = source_item.model_copy(update={"score": score, "source": source})
            _keep_best(best, candidate)

    return best


def _target_candidates(
    subquestions: Sequence[str],
    qdrant: QdrantSearcher | None,
    data_fato: date | None,
) -> dict[PairKey, RetrievedDevice]:
    if qdrant is None:
        raise ValueError("target path requires a qdrant searcher")

    best: dict[PairKey, RetrievedDevice] = {}
    for subquestion in subquestions:
        for raw in qdrant.search(subquestion, TARGET_BM25_LIMIT, data_fato):
            candidate = _as_retrieved(raw).model_copy(update={"source": "bm25"})
            _keep_best(best, candidate)
    return best


def _keep_best(best: dict[PairKey, RetrievedDevice], candidate: RetrievedDevice) -> None:
    key = _key(candidate)
    current = best.get(key)
    if current is None or candidate.score > current.score:
        best[key] = candidate


def _by_pair(items: Sequence[RetrievedDevice]) -> dict[PairKey, RetrievedDevice]:
    result: dict[PairKey, RetrievedDevice] = {}
    for item in items:
        key = _key(item)
        current = result.get(key)
        if current is None or item.score > current.score:
            result[key] = item
    return result


def _key(item: RetrievedDevice) -> PairKey:
    return (item.device_id, item.norm_version_id)


def _as_retrieved(item: Any) -> RetrievedDevice:
    if isinstance(item, RetrievedDevice):
        return item
    if isinstance(item, dict):
        return RetrievedDevice(
            device_id=item["device_id"],
            norm_version_id=item["norm_version_id"],
            score=float(item.get("score", 0.0)),
            source=item.get("source", "bm25"),
            texto_literal=item.get("texto_literal", ""),
            citacao=item.get("citacao", ""),
            vigencia=item.get("vigencia"),
            contexto=item.get("contexto"),
            explicacao=item.get("explicacao"),
        )
    return RetrievedDevice(
        device_id=item.device_id,
        norm_version_id=item.norm_version_id,
        score=float(item.score),
        source=getattr(item, "source", "bm25"),
        texto_literal=getattr(item, "texto_literal", "") or "",
        citacao=getattr(item, "citacao", "") or "",
        vigencia=getattr(item, "vigencia", None),
        contexto=getattr(item, "contexto", None),
        explicacao=getattr(item, "explicacao", None),
    )
