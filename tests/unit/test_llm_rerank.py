from __future__ import annotations

import pytest

from src.contracts import RetrievedDevice
from src.retrieve.llm_rerank import LLMReranker


def device(device_id: str, score: float, texto: str = "texto") -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=1,
        score=score,
        source="dense",
        texto_literal=texto,
        citacao=f"citacao {device_id}",
    )


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        self.prompts.append((system, user))
        return self.response


class BrokenLLM:
    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        raise RuntimeError("provider down")


def test_reranker_applies_the_requested_order() -> None:
    pool = [device("lmp/art5", 0.9), device("lmp/art7", 0.8), device("cp/art147", 0.7)]
    llm = FakeLLM('{"ids": ["cp/art147", "lmp/art5"]}')

    result = LLMReranker(llm)("pergunta", pool)

    assert [item.device_id for item in result][:3] == ["cp/art147", "lmp/art5", "lmp/art7"]
    assert result[0].source == "llm-rerank"
    assert result[0].score > result[1].score > result[2].score


def test_reranker_keeps_the_incoming_order_on_invalid_json() -> None:
    pool = [device("a", 0.9), device("b", 0.8)]

    assert LLMReranker(FakeLLM("nao sei")).__call__("q", pool) == pool


def test_reranker_keeps_the_incoming_order_when_the_provider_fails() -> None:
    pool = [device("a", 0.9), device("b", 0.8)]

    assert LLMReranker(BrokenLLM()).__call__("q", pool) == pool


def test_reranker_ignores_unknown_and_duplicated_ids() -> None:
    pool = [device("a", 0.9), device("b", 0.8)]
    llm = FakeLLM('{"ids": ["zzz", "b", "b", "a"]}')

    result = LLMReranker(llm)("q", pool)

    assert [item.device_id for item in result] == ["b", "a"]


def test_reranker_reads_a_fenced_json_answer() -> None:
    pool = [device("a", 0.9), device("b", 0.8)]
    llm = FakeLLM('```json\n{"ids": ["b"]}\n```')

    assert [item.device_id for item in LLMReranker(llm)("q", pool)] == ["b", "a"]


def test_reranker_prompt_lists_the_candidate_ids_and_truncates_text() -> None:
    pool = [device("lmp/art5", 0.9, texto="x" * 1000), device("lmp/art7", 0.5)]
    llm = FakeLLM('{"ids": []}')

    LLMReranker(llm, max_doc_chars=20)("pergunta", pool)

    system, user = llm.prompts[0]
    assert "id=lmp/art5" in user
    assert "x" * 20 in user
    assert "x" * 21 not in user


def test_reranker_rejects_a_non_positive_pool() -> None:
    with pytest.raises(ValueError, match="pool must be positive"):
        LLMReranker(FakeLLM("{}"), pool=0)
