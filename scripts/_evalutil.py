"""Shared helpers for the strategy sweeps (fusion, selection, metrics)."""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from typing import Any

from src.contracts import RetrievedDevice
from src.eval.metrics import article_recall_at_k, mrr_at_k, ndcg_at_k, recall_at_k
from src.retrieve.expand import dedupe_by_artigo
from src.retrieve.hybrid import rrf


def make_device(item: tuple[str, int], *, source: str = "dense") -> RetrievedDevice:
    return RetrievedDevice(
        device_id=item[0],
        norm_version_id=item[1],
        score=0.0,
        source=source,  # type: ignore[arg-type]
        texto_literal="",
        citacao=item[0],
    )


def select(
    dense: Sequence[tuple[str, int]],
    fts: Sequence[tuple[str, int]],
    *,
    weight: float = 0.2,
    rrf_k: int = 60,
    cap: int | None = 3,
    max_devices: int = 10,
    mode: str = "hybrid",
) -> list[RetrievedDevice]:
    """Fuse the two rank lists and apply the production selection rules."""

    if mode == "dense":
        fused: list[tuple[str, int]] = list(dense)
    elif mode == "fts":
        fused = list(fts)
    else:
        fused = [item for item, _ in rrf([list(dense), list(fts)], k=rrf_k, weights=[1.0, weight])]
    devices = [make_device(item) for item in fused]
    if cap is not None:
        devices = list(dedupe_by_artigo(devices, max_per_article=cap))
    return devices[:max_devices]


def fuse_many(
    lists: Sequence[Sequence[tuple[str, int]]],
    *,
    rrf_k: int = 60,
    cap: int | None = 3,
    max_devices: int = 10,
) -> list[RetrievedDevice]:
    """Fuse an arbitrary number of rank lists with equal weights."""

    fused = [item for item, _ in rrf([list(entry) for entry in lists], k=rrf_k)]
    devices = [make_device(item) for item in fused]
    if cap is not None:
        devices = list(dedupe_by_artigo(devices, max_per_article=cap))
    return devices[:max_devices]


def score_question(
    retrieved: Sequence[str], expected: Collection[str], *, k: int = 10
) -> dict[str, float]:
    return {
        "recall_at_10": recall_at_k(retrieved, expected, k),
        "article_recall_at_10": article_recall_at_k(retrieved, expected, k),
        "mrr_at_10": mrr_at_k(retrieved, expected, k),
        "ndcg_at_10": ndcg_at_k(retrieved, expected, k),
        "recall_at_50": recall_at_k(retrieved, expected, 50),
        "complete": float(set(expected) <= set(list(retrieved)[:k])),
    }


def aggregate(rows: Sequence[dict[str, float]], name: str) -> dict[str, Any]:
    count = len(rows) or 1
    merged: dict[str, Any] = {"name": name, "n": len(rows)}
    for metric in rows[0] if rows else {}:
        merged[metric] = round(sum(row[metric] for row in rows) / count, 4)
    return merged


def tokenize(text: str) -> list[str]:
    return [token for token in text.lower().split() if token]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    na = math.sqrt(sum(a * a for a in left))
    nb = math.sqrt(sum(b * b for b in right))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
