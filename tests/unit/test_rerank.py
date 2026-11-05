from __future__ import annotations

import math

from src.contracts import RetrievedDevice
from src.retrieve.rerank import maxsim_score, rerank


def candidate(device_id: str, score: float = 0.5) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=1,
        score=score,
        source="bm25",
        texto_literal=f"texto de {device_id}",
        citacao=f"citacao {device_id}",
    )


def test_maxsim_sums_max_cosine_per_query_token() -> None:
    query = [[1.0, 0.0], [0.0, 1.0]]
    doc = [[1.0, 0.0], [0.0, 1.0]]

    assert maxsim_score(query, doc) == 2.0


def test_maxsim_uses_the_best_doc_token_for_each_query_token() -> None:
    query = [[1.0, 0.0], [0.0, 1.0]]
    doc = [[1.0, 0.0], [0.6, 0.8]]

    assert maxsim_score(query, doc) == 1.0 + 0.8


def test_maxsim_handles_empty_and_zero_vectors() -> None:
    assert maxsim_score([], [[1.0, 0.0]]) == 0.0
    assert maxsim_score([[1.0, 0.0]], []) == 0.0
    assert maxsim_score([[0.0, 0.0]], [[1.0, 0.0]]) == 0.0


def test_maxsim_is_symmetric_in_scale() -> None:
    query = [[3.0, 4.0]]
    doc = [[6.0, 8.0]]

    assert math.isclose(maxsim_score(query, doc), 1.0)


class FakeEncoder:
    def __init__(self, query_vectors: list[list[float]], docs: dict[str, list[list[float]]]):
        self.query_vectors = query_vectors
        self.docs = docs
        self.encoded_query: str | None = None
        self.encoded_docs: list[str] | None = None

    def encode_query(self, text: str) -> list[list[float]]:
        self.encoded_query = text
        return self.query_vectors

    def encode_document(self, texts: list[str]) -> list[list[list[float]]]:
        self.encoded_docs = list(texts)
        return [self.docs[text] for text in texts]


def test_rerank_puts_the_correct_device_first_by_maxsim() -> None:
    encoder = FakeEncoder(
        [[[1.0, 0.0], [0.0, 1.0]]],
        {
            "texto de wrong": [[1.0, 0.0]],
            "texto de right": [[1.0, 0.0], [0.0, 1.0]],
        },
    )

    result = rerank(
        "proibição de contato",
        [candidate("wrong"), candidate("right")],
        encoder=encoder,
    )

    assert [item.device_id for item in result] == ["right", "wrong"]
    assert result[0].source == "maxsim"
    assert encoder.encoded_query == ["proibição de contato"]


def test_rerank_caps_at_ten_by_default() -> None:
    candidates = [candidate(f"d{index}") for index in range(12)]
    encoder = FakeEncoder(
        [[[1.0, 0.0]]],
        {item.texto_literal: [[1.0, 0.0]] for item in candidates},
    )

    result = rerank("p", candidates, encoder=encoder)

    assert len(result) == 10


def test_rerank_scores_at_most_fifty_candidates_in_fallback() -> None:
    candidates = [candidate(f"d{index:03d}") for index in range(150)]
    encoder = FakeEncoder(
        [[[1.0, 0.0]]],
        {item.texto_literal: [[1.0, 0.0]] for item in candidates},
    )

    result = rerank("p", candidates, encoder=encoder)

    assert encoder.encoded_docs is not None
    assert len(encoder.encoded_docs) == 50
    assert len(result) == 10


def test_rerank_without_encoder_keeps_rrf_order_and_source() -> None:
    candidates = [candidate("first", 0.9), candidate("second", 0.8)]

    result = rerank("p", candidates)

    assert [item.device_id for item in result] == ["first", "second"]
    assert [item.source for item in result] == ["bm25", "bm25"]
    assert [item.score for item in result] == [0.9, 0.8]


def test_rerank_output_is_monotonic_by_score() -> None:
    candidates = [candidate(f"d{index}") for index in range(5)]
    encoder = FakeEncoder(
        [[[1.0, 0.0]]],
        {item.texto_literal: [[1.0, float(index)]] for index, item in enumerate(candidates)},
    )

    result = rerank("p", candidates, encoder=encoder)

    scores = [item.score for item in result]
    assert scores == sorted(scores, reverse=True)


def test_target_rerank_delegates_to_rescore_over_all_candidates() -> None:
    candidates = [candidate(f"d{index}", score=float(index)) for index in range(150)]
    seen: list[int] = []

    def rescore(question: str, items: list[RetrievedDevice]) -> list[RetrievedDevice]:
        seen.append(len(items))
        return [
            item.model_copy(update={"score": 1.0 / (index + 1)})
            for index, item in enumerate(reversed(items))
        ]

    result = rerank("p", candidates, rescore=rescore)

    assert seen == [150]
    assert len(result) == 10
    assert result[0].device_id == "d149"
    assert all(item.source == "maxsim" for item in result)
