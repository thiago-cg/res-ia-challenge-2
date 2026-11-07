from __future__ import annotations

import math

import pytest

from src.eval.metrics import (
    abstention_accuracy,
    article_recall_at_k,
    citation_coverage,
    citation_precision,
    emergency_routing,
    groundedness,
    latency_percentiles,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    recall_per_question,
)


def test_recall_at_k_counts_each_expected_device_once() -> None:
    retrieved = ["a", "b", "a", "c"]
    assert recall_at_k(retrieved, {"a", "c"}, k=2) == 0.5
    assert recall_at_k(retrieved, {"a", "c"}, k=10) == 1.0
    assert recall_at_k(retrieved, set(), k=10) == 0.0


def test_recall_per_question_requires_every_expected_device() -> None:
    assert recall_per_question(["a", "c"], {"a", "c"}, k=10) == 1.0
    assert recall_per_question(["a", "b"], {"a", "c"}, k=10) == 0.0
    assert recall_per_question(["c", "a"], {"a", "c"}, k=1) == 0.0


def test_mrr_at_k_uses_the_first_relevant_rank() -> None:
    assert mrr_at_k(["a", "b", "c"], {"b"}, k=10) == 0.5
    assert mrr_at_k(["x", "y", "c"], {"c"}, k=3) == pytest.approx(1 / 3)
    assert mrr_at_k(["x"], {"c"}, k=10) == 0.0


def test_ndcg_at_k_matches_a_hand_computed_binary_case() -> None:
    # DCG = 1/log2(3); IDCG = 1.
    expected = 1 / math.log2(3)
    assert ndcg_at_k(["b", "a"], {"a"}, k=2) == pytest.approx(expected)
    assert ndcg_at_k(["a", "b"], {"a"}, k=2) == pytest.approx(1.0)
    assert ndcg_at_k(["b", "c"], {"a"}, k=2) == 0.0


def test_citation_precision_requires_retrieved_and_expected() -> None:
    assert citation_precision(["a", "x"], ["a", "b"], {"a", "b"}) == 0.5
    assert citation_precision(["a", "b"], ["a", "b"], {"a", "b"}) == 1.0
    assert citation_precision([], ["a"], {"a"}) == 0.0


def test_citation_coverage_and_groundedness() -> None:
    assert citation_coverage(["a"], {"a", "b"}) == 0.5
    assert citation_coverage([], {"a"}) == 0.0
    assert groundedness([True, False, True]) == pytest.approx(2 / 3)
    assert groundedness([]) == 0.0


def test_abstention_accuracy() -> None:
    assert abstention_accuracy([True, False, True], [True, False, False]) == pytest.approx(2 / 3)
    assert abstention_accuracy([], []) == 1.0
    with pytest.raises(ValueError):
        abstention_accuracy([True], [])


def test_emergency_routing_is_recall_over_expected_cases() -> None:
    assert emergency_routing([True, False, True], [True, True, False]) == 0.5
    assert emergency_routing([False, False], [False, False]) == 1.0
    with pytest.raises(ValueError):
        emergency_routing([True], [])


def test_latency_percentiles_use_nearest_rank() -> None:
    result = latency_percentiles([40, 10, 30, 20], (50, 95))
    assert result == {"p50": 20.0, "p95": 40.0}
    assert latency_percentiles([], (50, 95)) == {"p50": 0.0, "p95": 0.0}
    with pytest.raises(ValueError):
        latency_percentiles([1.0], (0,))


def test_article_recall_accepts_a_leaf_of_the_expected_article() -> None:
    # docs/05 dedupes by article, so a paragraph satisfies the article's gold.
    assert article_recall_at_k(["lmp/art5/cpt/inc3"], ["lmp/art5"]) == 1.0
    assert article_recall_at_k(["lmp/art19/par6"], ["lmp/art19/par5", "lmp/art19/par6"]) == 1.0


def test_article_recall_rejects_a_different_article() -> None:
    assert article_recall_at_k(["lmp/art6"], ["lmp/art5"]) == 0.0


def test_article_recall_returns_zero_without_expected_ids() -> None:
    assert article_recall_at_k(["lmp/art5"], []) == 0.0
