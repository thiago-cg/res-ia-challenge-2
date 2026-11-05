"""Pure evaluation metrics for the legal RAG prototype (EVA-02).

Every function takes plain Python values and returns a float (or a small
dictionary), so the metrics can be unit tested with hand-computed fixtures and
reused by any pipeline.  Empty inputs follow the documented conventions:

- retrieval and citation metrics return ``0.0`` when there is nothing to
  measure, instead of pretending a perfect score;
- ``emergency_routing`` returns ``1.0`` when no emergency case is expected
  (vacuously all expected cases were routed);
- ``abstention_accuracy`` returns ``1.0`` when both lists are empty.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence


def _top_k(retrieved: Sequence[str], k: int) -> list[str]:
    if k <= 0:
        return []
    return list(dict.fromkeys(retrieved))[:k]


def recall_at_k(retrieved: Sequence[str], expected: Collection[str], k: int = 10) -> float:
    """Fraction of expected device IDs found in the top ``k`` retrieved IDs."""

    expected_set = set(expected)
    if not expected_set:
        return 0.0
    found = set(_top_k(retrieved, k)) & expected_set
    return len(found) / len(expected_set)


def recall_per_question(retrieved: Sequence[str], expected: Collection[str], k: int = 10) -> float:
    """``1.0`` when every expected ID appears in the top ``k``, else ``0.0``."""

    expected_set = set(expected)
    if not expected_set:
        return 0.0
    return 1.0 if expected_set <= set(_top_k(retrieved, k)) else 0.0


def mrr_at_k(retrieved: Sequence[str], expected: Collection[str], k: int = 10) -> float:
    """Reciprocal rank of the first expected ID inside the top ``k``."""

    expected_set = set(expected)
    if not expected_set:
        return 0.0
    for rank, device_id in enumerate(_top_k(retrieved, k), start=1):
        if device_id in expected_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], expected: Collection[str], k: int = 10) -> float:
    """Binary-relevance nDCG@k for the expected device IDs."""

    expected_set = set(expected)
    if not expected_set:
        return 0.0

    top = _top_k(retrieved, k)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, device_id in enumerate(top, start=1)
        if device_id in expected_set
    )
    ideal_hits = min(len(expected_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def citation_precision(
    cited: Sequence[str],
    retrieved: Sequence[str],
    expected: Collection[str],
) -> float:
    """Fraction of citations that were retrieved and are expected by the gold set."""

    unique_cited = list(dict.fromkeys(cited))
    if not unique_cited:
        return 0.0
    supported = set(retrieved) & set(expected)
    return sum(1 for device_id in unique_cited if device_id in supported) / len(unique_cited)


def citation_coverage(cited: Sequence[str], expected: Collection[str]) -> float:
    """Fraction of expected device IDs that the answer cited."""

    expected_set = set(expected)
    if not expected_set:
        return 0.0
    return len(set(cited) & expected_set) / len(expected_set)


def groundedness(claims_supported: Sequence[bool]) -> float:
    """Fraction of legal claims that have support in a retrieved device."""

    if not claims_supported:
        return 0.0
    return sum(1 for claim in claims_supported if claim) / len(claims_supported)


def abstention_accuracy(predicted: Sequence[bool], expected: Sequence[bool]) -> float:
    """Accuracy of the abstention decision."""

    if len(predicted) != len(expected):
        raise ValueError("predicted and expected must have the same length")
    if not predicted:
        return 1.0
    hits = sum(1 for pred, exp in zip(predicted, expected, strict=True) if pred == exp)
    return hits / len(predicted)


def emergency_routing(routed: Sequence[bool], expected: Sequence[bool]) -> float:
    """Fraction of expected emergency cases that received the emergency block."""

    if len(routed) != len(expected):
        raise ValueError("routed and expected must have the same length")
    expected_cases = [pred for pred, exp in zip(routed, expected, strict=True) if exp]
    if not expected_cases:
        return 1.0
    return sum(1 for pred in expected_cases if pred) / len(expected_cases)


def latency_percentiles(
    latencies_ms: Sequence[float], percentiles: Sequence[int] = (50, 95)
) -> dict[str, float]:
    """Nearest-rank latency percentiles, e.g. ``{"p50": 20.0, "p95": 40.0}``."""

    for percentile in percentiles:
        if not 1 <= percentile <= 100:
            raise ValueError("percentiles must be between 1 and 100")

    if not latencies_ms:
        return {f"p{percentile}": 0.0 for percentile in percentiles}

    ordered = sorted(float(value) for value in latencies_ms)
    result: dict[str, float] = {}
    for percentile in percentiles:
        # Nearest-rank: ceil(p/100 * n) - 1, clamped to the list bounds.
        index = math.ceil(percentile / 100 * len(ordered)) - 1
        index = max(0, min(index, len(ordered) - 1))
        result[f"p{percentile}"] = ordered[index]
    return result
