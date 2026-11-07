from __future__ import annotations

import logging

import pytest

from src.contracts import RetrievedDevice
from src.retrieve.expand import dedupe_by_artigo, expand_to_article


def device(device_id: str, score: float, version: int = 1) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=version,
        score=score,
        source="maxsim",
        texto_literal=f"literal de {device_id}",
        citacao=f"citacao de {device_id}",
    )


class FakeArticleLookup:
    def __init__(self, articles: dict[tuple[str, int], dict[str, str]] | None = None) -> None:
        self.articles = articles or {}
        self.calls: list[tuple[str, int]] = []

    def lookup(self, artigo_id: str, norm_version_id: int) -> dict[str, str] | None:
        self.calls.append((artigo_id, norm_version_id))
        return self.articles.get((artigo_id, norm_version_id))


def test_three_leaves_of_same_article_collapse_to_one() -> None:
    candidates = [
        device("lmp/art22/cpt/inc3/ali-b", 0.8),
        device("lmp/art22/cpt/inc3/ali-c", 0.9),
        device("lmp/art22/cpt/inc4", 0.7),
    ]

    result = dedupe_by_artigo(candidates)

    assert len(result) == 1
    assert result[0].device_id == "lmp/art22/cpt/inc3/ali-c"


def test_dedupe_keeps_best_score_and_preserves_other_articles() -> None:
    candidates = [
        device("lmp/art7", 0.3),
        device("lmp/art22/cpt/inc3/ali-b", 0.5),
        device("lmp/art24", 0.9),
        device("lmp/art22/cpt/inc3/ali-c", 0.8),
    ]

    result = dedupe_by_artigo(candidates)

    assert [item.device_id for item in result] == [
        "lmp/art7",
        "lmp/art22/cpt/inc3/ali-c",
        "lmp/art24",
    ]


def test_dedupe_tie_breaks_deterministically_by_device_id() -> None:
    candidates = [
        device("lmp/art22/cpt/inc3/ali-c", 0.5),
        device("lmp/art22/cpt/inc3/ali-b", 0.5),
    ]

    result = dedupe_by_artigo(candidates)

    assert [item.device_id for item in result] == ["lmp/art22/cpt/inc3/ali-b"]


def test_dedupe_prefers_the_article_over_its_caput_duplicate() -> None:
    candidates = [
        device("lmp/art16-a/cpt", 0.9),
        device("lmp/art16-a", 0.8),
    ]

    result = dedupe_by_artigo(candidates)

    assert [item.device_id for item in result] == ["lmp/art16-a"]


def test_dedupe_prefers_a_deep_leaf_over_the_article() -> None:
    candidates = [
        device("lmp/art22", 0.9),
        device("lmp/art22/cpt/inc3/ali-b", 0.7),
    ]

    result = dedupe_by_artigo(candidates)

    assert [item.device_id for item in result] == ["lmp/art22/cpt/inc3/ali-b"]


def test_dedupe_preserves_versions_of_the_same_article() -> None:
    candidates = [
        device("lmp/art22/cpt/inc3", 0.5, version=1),
        device("lmp/art22/cpt/inc3", 0.6, version=2),
    ]

    result = dedupe_by_artigo(candidates)

    assert [(item.device_id, item.norm_version_id) for item in result] == [
        ("lmp/art22/cpt/inc3", 1),
        ("lmp/art22/cpt/inc3", 2),
    ]


def test_expand_prefers_article_context_and_keeps_leaf_citation() -> None:
    leaf = device("lmp/art22/cpt/inc3/ali-b", 0.8)
    lookup = FakeArticleLookup(
        {("lmp/art22", 1): {"texto_literal": "Art. 22. Texto completo do artigo."}}
    )

    result = expand_to_article([leaf], article_lookup=lookup)

    assert lookup.calls == [("lmp/art22", 1)]
    assert result.incomplete_context == []
    assert result.devices[0].device_id == leaf.device_id
    assert result.devices[0].score == leaf.score
    assert result.devices[0].citacao == leaf.citacao
    assert result.devices[0].texto_literal == leaf.texto_literal
    assert result.devices[0].contexto == "Art. 22. Texto completo do artigo."


def test_expand_lookup_miss_keeps_leaf_and_records_incomplete_context(
    caplog,
) -> None:
    leaf = device("lmp/art22/cpt/inc3/ali-b", 0.8)
    lookup = FakeArticleLookup()

    with caplog.at_level(logging.WARNING):
        result = expand_to_article([leaf], article_lookup=lookup)

    assert result.devices == [leaf]
    assert result.incomplete_context == [("lmp/art22", 1)]
    assert "incomplete_context" in caplog.text


def test_expand_uses_version_specific_lookup() -> None:
    candidates = [
        device("lmp/art22/cpt/inc3", 0.8, version=1),
        device("lmp/art22/cpt/inc3", 0.9, version=2),
    ]
    lookup = FakeArticleLookup(
        {
            ("lmp/art22", 1): {"texto_literal": "texto v1"},
            ("lmp/art22", 2): {"texto_literal": "texto v2"},
        }
    )

    result = expand_to_article(candidates, article_lookup=lookup)

    assert [item.contexto for item in result.devices] == ["texto v1", "texto v2"]
    assert result.incomplete_context == []


def test_expand_accepts_a_plain_callable() -> None:
    leaf = device("lmp/art22/cpt/inc3", 0.8)

    result = expand_to_article(
        [leaf],
        article_lookup=lambda artigo_id, version: {"texto_literal": f"{artigo_id}@{version}"},
    )

    assert result.devices[0].contexto == "lmp/art22@1"


def test_lookup_body_type_error_propagates_without_retry() -> None:
    calls: list[int] = []

    def lookup(artigo_id: str, version: int) -> dict[str, str]:
        calls.append(1)
        raise TypeError("boom inside lookup")

    with pytest.raises(TypeError, match="boom inside lookup"):
        expand_to_article([device("lmp/art22/cpt/inc3", 0.8)], article_lookup=lookup)

    assert calls == [1]


def test_lookup_with_one_parameter_receives_artigo_id() -> None:
    seen: list[str] = []

    def lookup(artigo_id: str) -> dict[str, str]:
        seen.append(artigo_id)
        return {"texto_literal": "artigo completo"}

    result = expand_to_article([device("lmp/art22/cpt/inc3", 0.8)], article_lookup=lookup)

    assert seen == ["lmp/art22"]
    assert result.devices[0].contexto == "artigo completo"


def test_ambiguous_lookup_signature_raises_before_calling() -> None:
    calls: list[int] = []

    def lookup(thing: object, version: int) -> dict[str, str] | None:
        calls.append(1)
        return None

    with pytest.raises(TypeError, match="ambiguous article_lookup signature"):
        expand_to_article([device("lmp/art22/cpt/inc3", 0.8)], article_lookup=lookup)

    assert calls == []
