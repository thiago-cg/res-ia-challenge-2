from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from src.eval.run import EvalQuestion, is_canonical_device_id, load_questions

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
QUESTIONS = DATA / "questions.jsonl"

VALID_CATEGORIES = {
    "prazo",
    "medida_protetiva",
    "acao_penal",
    "servicos",
    "emergencia",
    "fora_do_corpus",
}
VALID_DIFFICULTIES = {"baixa", "media", "alta"}
VALID_SPLITS = {"dev", "test"}


def _raw_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _questions() -> list[EvalQuestion]:
    return load_questions(QUESTIONS)


def test_exactly_twenty_valid_lines() -> None:
    rows = _raw_rows()
    assert len(rows) == 20
    assert len(_questions()) == 20


def test_ids_are_unique_and_sequential() -> None:
    questions = _questions()
    assert [question.id for question in questions] == [f"q{index:03d}" for index in range(1, 21)]


def test_questions_are_unique() -> None:
    normalized = [" ".join(question.pergunta.casefold().split()) for question in _questions()]
    duplicates = [text for text, count in Counter(normalized).items() if count > 1]
    assert duplicates == []


def test_schema_and_enums_are_valid() -> None:
    for question in _questions():
        assert question.categoria in VALID_CATEGORIES
        assert question.dificuldade in VALID_DIFFICULTIES
        assert question.split in VALID_SPLITS
        assert question.pergunta.strip()
        assert question.resposta_esperada.strip()
        assert question.fonte.strip()


def test_device_ids_are_canonical() -> None:
    for question in _questions():
        for device_id in question.device_ids:
            assert is_canonical_device_id(device_id), (question.id, device_id)


def test_only_emergency_and_out_of_corpus_have_no_device_ids() -> None:
    for question in _questions():
        if question.categoria in {"emergencia", "fora_do_corpus"}:
            assert question.device_ids == []
        else:
            assert question.device_ids, question.id


def test_at_least_five_abstention_and_five_emergency_cases() -> None:
    questions = _questions()
    assert sum(1 for question in questions if question.categoria == "fora_do_corpus") >= 5
    assert sum(1 for question in questions if question.categoria == "emergencia") >= 5


def test_every_category_appears() -> None:
    assert {question.categoria for question in _questions()} == VALID_CATEGORIES


def test_required_topics_are_covered() -> None:
    covered = {device_id for question in _questions() for device_id in question.device_ids}
    assert {
        "lmp/art16-a",
        "stj-sum-542",
        "lmp/art19/par5",
        "lmp/art19/par6",
        "lmp/art22/cpt/inc3/ali-b",
        "stj-sum-600",
        "cnj-rc-5-2020/art1",
        "lmp/art24-a",
    } <= covered


def test_at_least_one_historical_fact_before_lei_14550() -> None:
    historical = [
        question
        for question in _questions()
        if question.data_fato is not None and question.data_fato < date(2023, 4, 19)
    ]
    assert historical, "expected at least one data_fato before Lei 14.550/2023"


def test_splits_are_balanced() -> None:
    counts = Counter(question.split for question in _questions())
    assert counts["dev"] == counts["test"] == 10
