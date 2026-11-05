from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.eval.run import (
    DEFAULT_THRESHOLDS,
    PipelineResult,
    build_pipeline,
    load_questions,
    main,
    run_eval,
)

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
QUESTIONS = DATA / "questions.jsonl"


def perfect_pipeline(question: dict[str, Any]) -> PipelineResult:
    if question["categoria"] == "emergencia":
        return PipelineResult(answer="bloco de emergência", latency_ms=100.0, emergency=True)
    if question["categoria"] == "fora_do_corpus":
        return PipelineResult(answer="abstenção segura", latency_ms=100.0, abstained=True)

    ids = list(question["device_ids"])
    return PipelineResult(
        retrieved_ids=ids,
        answer="resposta fundamentada",
        latency_ms=100.0,
        citations=ids,
        claims_supported=[True],
    )


def partial_pipeline(question: dict[str, Any]) -> PipelineResult:
    if question["categoria"] == "emergencia":
        return PipelineResult(answer="bloco de emergência", latency_ms=200.0, emergency=True)
    if question["categoria"] == "fora_do_corpus":
        return PipelineResult(answer="abstenção segura", latency_ms=200.0, abstained=True)

    first = list(question["device_ids"])[:1]
    return PipelineResult(
        retrieved_ids=first,
        answer="resposta parcial",
        latency_ms=200.0,
        citations=first,
        claims_supported=[True],
    )


def abstaining_pipeline(question: dict[str, Any]) -> PipelineResult:
    return PipelineResult(answer="não sei", latency_ms=50.0, abstained=True)


@pytest.fixture()
def questions() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_perfect_pipeline_meets_default_thresholds(
    questions: list[dict[str, Any]], tmp_path: Path
) -> None:
    report = run_eval(
        questions,
        pipeline=perfect_pipeline,
        out_path=tmp_path / "last_run.json",
    )

    assert report.n_questions == 20
    assert report.recall_at_10 == 1.0
    assert report.recall_per_question == 1.0
    assert report.mrr_at_10 == 1.0
    assert report.ndcg_at_10 == 1.0
    assert report.citation_precision == 1.0
    assert report.citation_coverage == 1.0
    assert report.groundedness == 1.0
    assert report.abstention_accuracy == 1.0
    assert report.emergency_routing == 1.0
    assert report.latency_p50_ms == 100.0
    assert report.latency_p95_ms == 100.0
    assert report.failures == []
    assert report.threshold_failures == []
    assert report.passed is True


def test_partial_pipeline_fails_thresholds(questions: list[dict[str, Any]], tmp_path: Path) -> None:
    report = run_eval(
        questions,
        pipeline=partial_pipeline,
        out_path=tmp_path / "last_run.json",
    )

    assert report.recall_at_10 < 1.0
    assert report.recall_per_question < DEFAULT_THRESHOLDS["recall_per_question"]
    assert report.passed is False
    assert any("recall_at_10" in failure for failure in report.threshold_failures)
    assert report.failures


def test_always_abstaining_pipeline_is_penalized(
    questions: list[dict[str, Any]], tmp_path: Path
) -> None:
    report = run_eval(
        questions,
        pipeline=abstaining_pipeline,
        out_path=tmp_path / "last_run.json",
    )

    assert report.abstention_accuracy < 1.0
    assert report.emergency_routing == 0.0
    assert report.passed is False
    assert "q001" in report.failures
    assert "q011" in report.failures


def test_threshold_failure_is_reported(questions: list[dict[str, Any]], tmp_path: Path) -> None:
    report = run_eval(
        questions,
        pipeline=perfect_pipeline,
        thresholds={"recall_at_10": 1.01},
        out_path=tmp_path / "last_run.json",
    )

    assert report.passed is False
    assert report.threshold_failures == ["recall_at_10=1.0000 < 1.0100"]


def test_aggregates_by_category_and_difficulty(
    questions: list[dict[str, Any]], tmp_path: Path
) -> None:
    report = run_eval(
        questions,
        pipeline=perfect_pipeline,
        out_path=tmp_path / "last_run.json",
    )

    assert report.by_category["prazo"].count == 2
    assert report.by_category["prazo"].recall_at_10 == 1.0
    assert report.by_category["emergencia"].count == 5
    assert report.by_category["emergencia"].emergency_routing == 1.0
    assert report.by_category["fora_do_corpus"].abstention_accuracy == 1.0
    assert report.by_difficulty["alta"].count > 0


def test_report_is_written_as_json(questions: list[dict[str, Any]], tmp_path: Path) -> None:
    out = tmp_path / "nested" / "last_run.json"
    report = run_eval(questions, pipeline=perfect_pipeline, out_path=out)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["run_id"] == report.run_id
    assert payload["n_questions"] == 20
    assert payload["passed"] is True


def test_pipeline_receives_the_raw_question_mapping(
    questions: list[dict[str, Any]], tmp_path: Path
) -> None:
    received: list[dict[str, Any]] = []

    def spy(question: dict[str, Any]) -> PipelineResult:
        received.append(question)
        return perfect_pipeline(question)

    run_eval(questions, pipeline=spy, out_path=tmp_path / "last_run.json")
    assert received[0]["id"] == "q001"
    assert received[0]["categoria"] == "prazo"


def test_empty_questions_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_eval([], pipeline=perfect_pipeline, out_path=tmp_path / "last_run.json")


def test_load_questions_reports_invalid_json(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_questions(broken)


def test_cli_uses_injected_pipeline(questions: list[dict[str, Any]], tmp_path: Path) -> None:
    source = tmp_path / "questions.jsonl"
    source.write_text(
        "\n".join(json.dumps(question, ensure_ascii=False) for question in questions) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "last_run.json"

    code = main(
        ["--questions", str(source), "--out", str(out)],
        pipeline_factory=lambda: perfect_pipeline,
    )

    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["passed"] is True


def test_cli_returns_one_when_threshold_fails(
    questions: list[dict[str, Any]], tmp_path: Path
) -> None:
    source = tmp_path / "questions.jsonl"
    source.write_text(
        "\n".join(json.dumps(question, ensure_ascii=False) for question in questions) + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "--questions",
            str(source),
            "--out",
            str(tmp_path / "last_run.json"),
            "--fail-under",
            "1.01",
        ],
        pipeline_factory=lambda: perfect_pipeline,
    )

    assert code == 1


def test_cli_reports_missing_pipeline(
    questions: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "questions.jsonl"
    source.write_text(
        "\n".join(json.dumps(question, ensure_ascii=False) for question in questions) + "\n",
        encoding="utf-8",
    )

    def unavailable() -> None:
        raise RuntimeError("pipeline real de avaliação indisponível")

    monkeypatch.setattr("src.eval.run.build_pipeline", unavailable)
    code = main(["--questions", str(source), "--out", str(tmp_path / "last_run.json")])
    assert code == 2


def test_build_pipeline_fails_with_clear_message() -> None:
    with pytest.raises(RuntimeError, match="pipeline real de avaliação indisponível"):
        build_pipeline()
