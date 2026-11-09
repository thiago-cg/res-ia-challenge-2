"""Pins the retrieval profile chosen by the nov/2026 benchmark.

The defaults in `Settings` are a decision, not an accident: they were chosen on
the 110 answerable questions, and the reasoning lives in
docs/reviews/estrategia-recomendada.md.  This module makes that decision
explicit, so changing one of these values requires changing the document (and
this test) in the same commit rather than drifting in silence.

To change it on purpose: re-run scripts/sweep_retrieval.py and
scripts/benchmark_e2e.py, update the document, then update this test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import Settings
from src.contracts import RetrievedDevice
from src.retrieve.expand import dedupe_by_artigo

CANONICAL_DOC = (
    Path(__file__).resolve().parents[2] / "docs" / "reviews" / "estrategia-recomendada.md"
)


def _default(name: str) -> Any:
    return Settings.model_fields[name].default


def test_retrieval_profile_matches_the_benchmarked_decision() -> None:
    assert _default("hybrid_lexical_weight") == 0.2, (
        "heavy lexical weights measured worse: 0.576 at 1.0 against 0.771 at 0.2"
    )
    assert _default("max_devices_per_article") == 3, (
        "cap 3 keeps diversity of norms without dropping sibling devices"
    )
    assert _default("query_expansion") is True, (
        "deterministic expansion is worth 13 points of recall@10"
    )
    assert _default("query_rewrite") == "none", (
        "every LLM rewrite lost to the deterministic rules: 0.539 against 0.758"
    )
    assert _default("rerank_provider") == "none", (
        "the LLM reranker costs 20 points of device-level recall under the "
        "device contract; revisit only if citations become article-level"
    )
    assert _default("llm_max_tokens") == 0, (
        "a token cap truncates the reasoning model JSON and fails verification"
    )


def _device(device_id: str, score: float) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=7,
        score=score,
        source="dense",
        texto_literal="",
        citacao=device_id,
    )


def test_dedupe_cap_keeps_the_global_order() -> None:
    # The ordering is the whole point: regrouping by article cost 11 points of
    # recall@10 and did not help article-level recall either.
    candidates = [
        _device("lmp/art19/par5", 0.9),
        _device("lmp/art19", 0.4),
        _device("lmp/art19/par6", 0.7),
        _device("lmp/art5", 0.3),
    ]

    capped = dedupe_by_artigo(candidates, max_per_article=3)

    assert [item.device_id for item in capped] == [
        "lmp/art19/par5",
        "lmp/art19",
        "lmp/art19/par6",
        "lmp/art5",
    ]


def test_dedupe_cap_actually_limits_per_article() -> None:
    candidates = [
        _device("lmp/art19/par5", 1.0),
        _device("lmp/art19/par6", 0.9),
        _device("lmp/art19/par1", 0.8),
        _device("lmp/art5", 0.7),
    ]

    capped = dedupe_by_artigo(candidates, max_per_article=2)

    assert [item.device_id for item in capped] == [
        "lmp/art19/par5",
        "lmp/art19/par6",
        "lmp/art5",
    ]


def test_canonical_strategy_document_exists() -> None:
    assert CANONICAL_DOC.is_file(), (
        "the decision is recorded in docs/reviews/estrategia-recomendada.md; "
        "deleting it leaves the defaults unexplained"
    )
