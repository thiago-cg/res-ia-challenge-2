from __future__ import annotations

from datetime import date

import pytest

from src.contracts import QueryFacts, QueryPlan, RetrievedDevice
from src.index.pgvector import SearchHit
from src.retrieve.hybrid import hybrid_search, rrf


def make_plan(*subperguntas: str) -> QueryPlan:
    return QueryPlan(
        fatos=QueryFacts(
            relacao="desconhecido",
            tipo_violencia=[],
            urgencia="desconhecida",
            data_fato=None,
            uf=None,
        ),
        consulta_juridica=subperguntas[0] if subperguntas else "",
        subperguntas=list(subperguntas) or ["pergunta"],
    )


def hit(device_id: str, version: int = 1, score: float = 1.0) -> SearchHit:
    return SearchHit(device_id=device_id, norm_version_id=version, score=score, source="dense")


def retrieved(device_id: str, version: int = 1, score: float = 1.0) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=version,
        score=score,
        source="bm25",
        texto_literal="",
        citacao="",
    )


class FakeSearcher:
    def __init__(self, results: dict[str, list] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, int, date | None]] = []

    def search(self, query: str, limit: int, data_fato: date | None = None) -> list:
        self.calls.append((query, limit, data_fato))
        return list(self.results.get(query, []))


def test_rrf_matches_documented_formula_and_order() -> None:
    merged = rrf([["a", "b"], ["b", "c"]], k=60)

    assert [item[0] for item in merged] == ["b", "a", "c"]
    assert merged[0][1] == 1 / 61 + 1 / 62
    assert merged[1][1] == 1 / 61
    assert merged[2][1] == 1 / 62


def test_rrf_accepts_custom_k() -> None:
    merged = rrf([["a"], ["b"]], k=1)

    assert [item[0] for item in merged] == ["a", "b"]
    assert merged[0][1] == 0.5


def test_fallback_searches_top_50_dense_and_fts_per_subquestion() -> None:
    dense = FakeSearcher({"p1": [hit("d1")], "p2": [hit("d2")]})
    fts = FakeSearcher({"p1": [hit("f1")], "p2": [hit("f2")]})

    result = hybrid_search(
        make_plan("p1", "p2"),
        dense=dense,
        fts=fts,
        path="fallback",
    )

    assert [call[:2] for call in dense.calls] == [("p1", 50), ("p2", 50)]
    assert [call[:2] for call in fts.calls] == [("p1", 50), ("p2", 50)]
    assert {item.device_id for item in result} == {"d1", "f1", "d2", "f2"}


def test_fallback_merges_with_rrf_and_marks_sources() -> None:
    dense = FakeSearcher({"p": [hit("only-dense"), hit("both")]})
    fts = FakeSearcher({"p": [hit("both"), hit("only-fts")]})

    result = hybrid_search(make_plan("p"), dense=dense, fts=fts)

    by_id = {item.device_id: item for item in result}
    assert by_id["both"].source == "bm25"
    assert by_id["only-fts"].source == "bm25"
    assert by_id["only-dense"].source == "dense"


def test_fallback_caps_union_at_150() -> None:
    names = ("p0", "p1", "p2")
    dense = FakeSearcher({name: [hit(f"d{name}-{index}") for index in range(50)] for name in names})
    fts = FakeSearcher({name: [hit(f"f{name}-{index}") for index in range(50)] for name in names})

    result = hybrid_search(make_plan(*names), dense=dense, fts=fts)

    assert len(result) == 150


def test_three_subquestions_are_all_searched() -> None:
    dense = FakeSearcher({name: [hit(name)] for name in ("p1", "p2", "p3")})
    fts = FakeSearcher({name: [hit(f"fts-{name}")] for name in ("p1", "p2", "p3")})

    result = hybrid_search(make_plan("p1", "p2", "p3"), dense=dense, fts=fts)

    assert [call[0] for call in dense.calls] == ["p1", "p2", "p3"]
    assert {item.device_id for item in result} == {
        "p1",
        "p2",
        "p3",
        "fts-p1",
        "fts-p2",
        "fts-p3",
    }


def test_date_filter_is_forwarded_to_searchers() -> None:
    fato = date(2010, 5, 1)
    dense = FakeSearcher({"p": [hit("d1")]})
    fts = FakeSearcher({"p": [hit("f1")]})

    hybrid_search(make_plan("p"), dense=dense, fts=fts, data_fato=fato)

    assert dense.calls[0][2] == fato
    assert fts.calls[0][2] == fato


def test_empty_results_return_empty_list_without_error() -> None:
    result = hybrid_search(make_plan("p"), dense=FakeSearcher(), fts=FakeSearcher())

    assert result == []


def test_target_path_uses_qdrant_top_100_and_caps_150() -> None:
    qdrant = FakeSearcher(
        {
            "p1": [retrieved(f"q{index}") for index in range(100)],
            "p2": [retrieved(f"r{index}") for index in range(100)],
        }
    )
    dense = FakeSearcher()
    fts = FakeSearcher()

    result = hybrid_search(
        make_plan("p1", "p2"),
        dense=dense,
        fts=fts,
        qdrant=qdrant,
        path="target",
    )

    assert [call[:2] for call in qdrant.calls] == [("p1", 100), ("p2", 100)]
    assert dense.calls == []
    assert fts.calls == []
    assert len(result) == 150
    assert all(item.source == "bm25" for item in result)


def test_target_path_keeps_version_pairs_distinct() -> None:
    qdrant = FakeSearcher(
        {
            "p": [
                retrieved("lmp/art22", version=1, score=0.4),
                retrieved("lmp/art22", version=2, score=0.9),
            ]
        }
    )

    result = hybrid_search(
        make_plan("p"), dense=FakeSearcher(), fts=FakeSearcher(), qdrant=qdrant, path="target"
    )

    assert [(item.device_id, item.norm_version_id) for item in result] == [
        ("lmp/art22", 2),
        ("lmp/art22", 1),
    ]


def test_fallback_defensively_truncates_searcher_output_to_50() -> None:
    dense = FakeSearcher({"p": [hit(f"d{index}") for index in range(60)]})
    fts = FakeSearcher({"p": []})

    result = hybrid_search(make_plan("p"), dense=dense, fts=fts)

    assert len(result) == 50
    assert result[0].device_id == "d0"
    assert all(item.device_id != "d50" for item in result)


def test_target_defensively_truncates_searcher_output_to_100() -> None:
    qdrant = FakeSearcher({"p": [retrieved(f"q{index}") for index in range(120)]})

    result = hybrid_search(
        make_plan("p"),
        dense=FakeSearcher(),
        fts=FakeSearcher(),
        qdrant=qdrant,
        path="target",
    )

    assert len(result) == 100
    assert all(item.device_id != "q100" for item in result)


def test_rrf_accepts_weights_per_list() -> None:
    dense = ["a", "b"]
    lexical = ["c"]

    assert [key for key, _ in rrf([dense, lexical], weights=[1.0, 0.0])] == ["a", "b"]
    assert [key for key, _ in rrf([dense, lexical], weights=[0.0, 1.0])] == ["c"]


def test_rrf_rejects_mismatched_or_negative_weights() -> None:
    with pytest.raises(ValueError, match="weights must match"):
        rrf([["a"], ["b"]], weights=[1.0])
    with pytest.raises(ValueError, match="weights must be non-negative"):
        rrf([["a"]], weights=[-1.0])
