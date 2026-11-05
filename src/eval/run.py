"""Evaluation harness with an injectable pipeline (EVA-02).

The harness itself never touches Postgres, Qdrant, an embedder, or an LLM.
Callers inject ``pipeline(question) -> PipelineResult``; the real pipeline is
wired only by the CLI through :func:`build_pipeline`, which imports the adapter
lazily and fails with a clear message when it is unavailable.

The default ``out_path`` is ``data/eval/last_run.json`` as described in
docs/08 §8.  Tests pass a temporary path so the repository stays clean.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.eval.metrics import (
    abstention_accuracy,
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

K = 10
DEFAULT_REPORT_PATH = Path("data/eval/last_run.json")
DEFAULT_QUESTIONS_PATH = Path("data/eval/questions.jsonl")

Categoria = Literal[
    "prazo",
    "medida_protetiva",
    "acao_penal",
    "servicos",
    "emergencia",
    "fora_do_corpus",
]
Dificuldade = Literal["baixa", "media", "alta"]
Split = Literal["dev", "test"]

CANONICAL_DEVICE_ID_RE = re.compile(
    r"^(?:"
    r"(?:lmp|cp|cpp|cf|lgpd|lda|lei-15438-2026|lei-14994-2024|"
    r"cnj-rc-5-2020|cnj-portaria-6-2025)"
    r"/art\d+(?:-[a-z])?"
    r"(?:/(?:cpt|par-unico|par\d+|inc\d+|ali-[a-z]|item-\d+))*"
    r"|stj-sum-\d+"
    r"|stf-adi-\d+"
    r")$"
)

DEFAULT_THRESHOLDS: dict[str, float] = {
    "recall_at_10": 0.85,
    "recall_per_question": 0.70,
    "mrr_at_10": 0.60,
    "ndcg_at_10": 0.70,
    "citation_precision": 0.95,
    "citation_coverage": 0.80,
    "groundedness": 0.95,
    "abstention_accuracy": 0.80,
    "emergency_routing": 1.0,
    # Maximum, not minimum: latency above this value fails the threshold.
    "latency_p95_ms": 8000.0,
}


class EvalQuestion(BaseModel):
    id: str
    pergunta: str
    device_ids: list[str] = Field(default_factory=list)
    categoria: Categoria
    data_fato: date | None = None
    resposta_esperada: str
    fonte: str
    dificuldade: Dificuldade
    split: Split
    revisao: Literal["pendente", "revisada"] | None = None


@dataclass(frozen=True)
class PipelineResult:
    """What the harness needs from one pipeline execution."""

    retrieved_ids: Sequence[str] = ()
    answer: str = ""
    latency_ms: float = 0.0
    emergency: bool = False
    citations: Sequence[str] = ()
    abstained: bool = False
    claims_supported: Sequence[bool] = ()


Pipeline = Callable[[Mapping[str, Any]], PipelineResult | Mapping[str, Any]]


class MetricSet(BaseModel):
    recall_at_10: float = 0.0
    recall_per_question: float = 0.0
    mrr_at_10: float = 0.0
    ndcg_at_10: float = 0.0
    citation_precision: float = 0.0
    citation_coverage: float = 0.0
    groundedness: float = 0.0
    abstention_accuracy: float | None = 0.0
    emergency_routing: float | None = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0


class Aggregate(MetricSet):
    count: int = 0


class EvalReport(MetricSet):
    run_id: str
    n_questions: int
    thresholds: dict[str, float] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    threshold_failures: list[str] = Field(default_factory=list)
    passed: bool = True
    by_category: dict[str, Aggregate] = Field(default_factory=dict)
    by_difficulty: dict[str, Aggregate] = Field(default_factory=dict)


def is_canonical_device_id(value: str) -> bool:
    return CANONICAL_DEVICE_ID_RE.match(value) is not None


def load_questions(path: str | Path) -> list[EvalQuestion]:
    """Load and validate a JSONL question file."""

    questions: list[EvalQuestion] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        try:
            questions.append(EvalQuestion.model_validate(payload))
        except Exception as exc:
            raise ValueError(f"{path}:{line_number}: invalid question: {exc}") from exc
    return questions


def _as_question(item: EvalQuestion | Mapping[str, Any]) -> tuple[EvalQuestion, dict[str, Any]]:
    if isinstance(item, EvalQuestion):
        return item, item.model_dump(mode="json")
    if isinstance(item, Mapping):
        payload = dict(item)
        return EvalQuestion.model_validate(payload), payload
    raise TypeError(f"question must be EvalQuestion or mapping, got {type(item)!r}")


def _coerce_result(value: Any) -> PipelineResult:
    if isinstance(value, PipelineResult):
        return value
    if isinstance(value, Mapping):
        return PipelineResult(
            retrieved_ids=list(value.get("retrieved_ids", ())),
            answer=str(value.get("answer", "")),
            latency_ms=float(value.get("latency_ms", 0.0)),
            emergency=bool(value.get("emergency", False)),
            citations=list(value.get("citations", ())),
            abstained=bool(value.get("abstained", False)),
            claims_supported=[bool(claim) for claim in value.get("claims_supported", ())],
        )
    if hasattr(value, "retrieved_ids"):
        return PipelineResult(
            retrieved_ids=list(value.retrieved_ids),
            answer=str(value.answer),
            latency_ms=float(value.latency_ms),
            emergency=bool(value.emergency),
            citations=list(value.citations),
            abstained=bool(value.abstained),
            claims_supported=[bool(claim) for claim in value.claims_supported],
        )
    raise TypeError(f"pipeline must return PipelineResult or mapping, got {type(value)!r}")


def _is_emergency(question: EvalQuestion) -> bool:
    return question.categoria == "emergencia"


def _expects_abstention(question: EvalQuestion) -> bool:
    return question.categoria == "fora_do_corpus"


def _is_answerable(question: EvalQuestion) -> bool:
    return (
        bool(question.device_ids)
        and not _is_emergency(question)
        and not _expects_abstention(question)
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _question_metrics(question: EvalQuestion, result: PipelineResult) -> dict[str, float]:
    if not _is_answerable(question):
        return {
            "recall_at_10": 0.0,
            "recall_per_question": 0.0,
            "mrr_at_10": 0.0,
            "ndcg_at_10": 0.0,
            "citation_precision": 0.0,
            "citation_coverage": 0.0,
            "groundedness": 0.0,
        }

    expected = question.device_ids
    return {
        "recall_at_10": recall_at_k(result.retrieved_ids, expected, K),
        "recall_per_question": recall_per_question(result.retrieved_ids, expected, K),
        "mrr_at_10": mrr_at_k(result.retrieved_ids, expected, K),
        "ndcg_at_10": ndcg_at_k(result.retrieved_ids, expected, K),
        "citation_precision": citation_precision(result.citations, result.retrieved_ids, expected),
        "citation_coverage": citation_coverage(result.citations, expected),
        "groundedness": groundedness(result.claims_supported),
    }


def _aggregate(questions: Sequence[EvalQuestion], results: Sequence[PipelineResult]) -> Aggregate:
    answerable = [
        _question_metrics(question, result)
        for question, result in zip(questions, results, strict=True)
        if _is_answerable(question)
    ]

    non_emergency = [
        (question, result)
        for question, result in zip(questions, results, strict=True)
        if not _is_emergency(question)
    ]
    emergency = [
        (question, result)
        for question, result in zip(questions, results, strict=True)
        if _is_emergency(question)
    ]
    latencies = [result.latency_ms for result in results]
    percentiles = latency_percentiles(latencies)
    abstention_value = (
        abstention_accuracy(
            [result.abstained for _, result in non_emergency],
            [_expects_abstention(question) for question, _ in non_emergency],
        )
        if non_emergency
        else None
    )
    emergency_value = (
        emergency_routing(
            [result.emergency for _, result in emergency],
            [True for _ in emergency],
        )
        if emergency
        else None
    )

    return Aggregate(
        count=len(questions),
        recall_at_10=_mean([item["recall_at_10"] for item in answerable]),
        recall_per_question=_mean([item["recall_per_question"] for item in answerable]),
        mrr_at_10=_mean([item["mrr_at_10"] for item in answerable]),
        ndcg_at_10=_mean([item["ndcg_at_10"] for item in answerable]),
        citation_precision=_mean([item["citation_precision"] for item in answerable]),
        citation_coverage=_mean([item["citation_coverage"] for item in answerable]),
        groundedness=_mean([item["groundedness"] for item in answerable]),
        abstention_accuracy=abstention_value,
        emergency_routing=emergency_value,
        latency_p50_ms=percentiles["p50"],
        latency_p95_ms=percentiles["p95"],
    )


def _question_failed(question: EvalQuestion, result: PipelineResult) -> bool:
    if _is_emergency(question):
        return not result.emergency
    if _expects_abstention(question):
        return not result.abstained
    if result.abstained:
        return True

    expected = set(question.device_ids)
    top = set(result.retrieved_ids[:K])
    cited = set(result.citations)
    return (
        not expected <= top
        or not expected <= cited
        or any(claim is False for claim in result.claims_supported)
    )


def _threshold_failures(report: EvalReport) -> list[str]:
    failures: list[str] = []
    for name, limit in report.thresholds.items():
        value = getattr(report, name, None)
        if value is None:
            continue
        if name == "latency_p95_ms":
            if value > limit:
                failures.append(f"{name}={value:.4f} > {limit:.4f}")
        elif value < limit:
            failures.append(f"{name}={value:.4f} < {limit:.4f}")
    return failures


def run_eval(
    questions: Sequence[EvalQuestion | Mapping[str, Any]],
    *,
    pipeline: Pipeline,
    thresholds: Mapping[str, float] | None = None,
    out_path: str | Path | None = DEFAULT_REPORT_PATH,
    run_id: str | None = None,
) -> EvalReport:
    """Run every question through ``pipeline`` and aggregate the metrics."""

    if not questions:
        raise ValueError("at least one question is required")

    normalized: list[EvalQuestion] = []
    results: list[PipelineResult] = []
    for item in questions:
        question, payload = _as_question(item)
        normalized.append(question)
        results.append(_coerce_result(pipeline(payload)))

    overall = _aggregate(normalized, results)
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds is not None:
        active_thresholds.update(thresholds)

    report = EvalReport(
        run_id=run_id or datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S"),
        n_questions=len(normalized),
        thresholds=active_thresholds,
        **overall.model_dump(exclude={"count", "abstention_accuracy", "emergency_routing"}),
        abstention_accuracy=overall.abstention_accuracy or 0.0,
        emergency_routing=overall.emergency_routing or 0.0,
        failures=[
            question.id
            for question, result in zip(normalized, results, strict=True)
            if _question_failed(question, result)
        ],
        by_category={
            category: _aggregate(
                [question for question in normalized if question.categoria == category],
                [
                    result
                    for question, result in zip(normalized, results, strict=True)
                    if question.categoria == category
                ],
            )
            for category in dict.fromkeys(question.categoria for question in normalized)
        },
        by_difficulty={
            difficulty: _aggregate(
                [question for question in normalized if question.dificuldade == difficulty],
                [
                    result
                    for question, result in zip(normalized, results, strict=True)
                    if question.dificuldade == difficulty
                ],
            )
            for difficulty in dict.fromkeys(question.dificuldade for question in normalized)
        },
    )
    report.threshold_failures = _threshold_failures(report)
    report.passed = not report.threshold_failures

    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return report


def build_pipeline() -> Pipeline:
    """Load the real pipeline adapter; fail clearly when it is not available."""

    try:
        module = importlib.import_module("src.api.main")
        factory = module.build_eval_pipeline
    except Exception as exc:
        raise RuntimeError(
            "pipeline real de avaliação indisponível: esperado "
            "src.api.main.build_eval_pipeline; nenhum adaptador com Postgres/Qdrant "
            "foi encontrado. O harness aceita um pipeline injetado nos testes. "
            f"Detalhe: {exc}"
        ) from exc

    pipeline = factory()
    if not callable(pipeline):
        raise RuntimeError("src.api.main.build_eval_pipeline não retornou um callable")
    return pipeline


def main(
    argv: Sequence[str] | None = None,
    *,
    pipeline_factory: Callable[[], Pipeline] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run the legal RAG evaluation harness.")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="sobrescreve o limite mínimo de recall@10; retorna código 1 se falhar",
    )
    args = parser.parse_args(argv)

    try:
        questions = load_questions(args.questions)
    except (OSError, ValueError) as exc:
        print(f"erro ao carregar perguntas: {exc}", file=sys.stderr)
        return 2

    try:
        pipeline = pipeline_factory() if pipeline_factory is not None else build_pipeline()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.fail_under is not None:
        thresholds["recall_at_10"] = args.fail_under

    try:
        report = run_eval(
            questions,
            pipeline=pipeline,
            thresholds=thresholds,
            out_path=args.out,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"erro ao executar avaliação: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
