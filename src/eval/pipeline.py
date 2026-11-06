"""Adapter from the chat pipeline to the evaluation harness (EVA-02)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, Protocol

from src.contracts import Answer, QueryFacts
from src.eval.run import PipelineResult


class ChatPipeline(Protocol):
    def answer(self, message: str, facts: QueryFacts | None = None) -> Any: ...


def make_eval_pipeline(
    pipeline: ChatPipeline,
) -> Callable[[Mapping[str, Any]], PipelineResult]:
    """Wrap a chat pipeline in the mapping contract used by ``run_eval``."""

    def run(question: Mapping[str, Any]) -> PipelineResult:
        facts = facts_from_question(question)
        started = time.perf_counter()
        result = pipeline.answer(str(question.get("pergunta", "")), facts)
        latency_ms = (time.perf_counter() - started) * 1000.0

        answer: Answer = result.answer
        citations = [citation.device_id for citation in answer.citacoes]
        abstained = bool(answer.abstencao)
        emergency = bool(result.emergencia)
        return PipelineResult(
            retrieved_ids=tuple(result.retrieved_ids),
            answer=answer.resposta,
            latency_ms=latency_ms,
            emergency=emergency,
            citations=citations,
            abstained=abstained,
            claims_supported=[] if abstained or emergency else [True] * len(citations),
        )

    return run


def facts_from_question(question: Mapping[str, Any]) -> QueryFacts:
    """Map the eval question fields to the query facts contract."""

    return QueryFacts(
        relacao="desconhecido",
        tipo_violencia=[],
        urgencia="desconhecida",
        data_fato=_parse_date(question.get("data_fato")),
        uf=None,
    )


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
