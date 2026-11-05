from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.eval.run import EvalQuestion, is_canonical_device_id, load_questions

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
QUESTIONS = DATA / "questions.jsonl"
QUESTIONS_150 = DATA / "questions_150.jsonl"

VALID_CATEGORIES = {
    "prazo",
    "medida_protetiva",
    "acao_penal",
    "servicos",
    "emergencia",
    "fora_do_corpus",
}
VALID_DIFFICULTIES = {"baixa", "media", "alta"}


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def test_exactly_one_hundred_and_fifty_valid_questions() -> None:
    questions = load_questions(QUESTIONS_150)
    assert len(questions) == 150
    assert [question.id for question in questions] == [f"q{index:03d}" for index in range(1, 151)]


def test_questions_are_unique() -> None:
    questions = load_questions(QUESTIONS_150)
    normalized = Counter(_normalize(question.pergunta) for question in questions)
    assert [text for text, count in normalized.items() if count > 1] == []


def test_seeded_twenty_are_an_exact_subset() -> None:
    seeded = {question.id: question for question in load_questions(QUESTIONS)}
    combined = {question.id: question for question in load_questions(QUESTIONS_150)}
    for question_id, question in seeded.items():
        assert combined[question_id] == question


def test_synthetic_additions_are_marked() -> None:
    questions = load_questions(QUESTIONS_150)
    for question in questions[20:]:
        assert question.fonte == "sintetica", question.id


def test_schema_enums_and_text_are_valid() -> None:
    for question in load_questions(QUESTIONS_150):
        assert question.categoria in VALID_CATEGORIES
        assert question.dificuldade in VALID_DIFFICULTIES
        assert question.split in {"dev", "test"}
        assert question.pergunta.strip()
        assert question.resposta_esperada.strip()
        assert question.fonte.strip()


def test_device_ids_are_canonical() -> None:
    for question in load_questions(QUESTIONS_150):
        for device_id in question.device_ids:
            assert is_canonical_device_id(device_id), (question.id, device_id)


def test_only_emergency_and_out_of_corpus_have_no_device_ids() -> None:
    for question in load_questions(QUESTIONS_150):
        if question.categoria in {"emergencia", "fora_do_corpus"}:
            assert question.device_ids == [], question.id
        else:
            assert question.device_ids, question.id


def test_at_least_twenty_abstention_and_twenty_emergency_cases() -> None:
    questions = load_questions(QUESTIONS_150)
    assert sum(1 for question in questions if question.categoria == "fora_do_corpus") >= 20
    assert sum(1 for question in questions if question.categoria == "emergencia") >= 20


def test_splits_are_present_and_balanced() -> None:
    counts = Counter(question.split for question in load_questions(QUESTIONS_150))
    assert counts["dev"] > 0
    assert counts["test"] > 0
    assert abs(counts["dev"] - counts["test"]) <= 20


def test_every_category_appears() -> None:
    categories = {question.categoria for question in load_questions(QUESTIONS_150)}
    assert categories == VALID_CATEGORIES


def test_answers_are_non_empty_strings() -> None:
    for question in load_questions(QUESTIONS_150):
        assert isinstance(question.resposta_esperada, str)
        assert question.resposta_esperada.strip()


def test_question_type_is_homogeneous_with_seed() -> None:
    seeded: list[EvalQuestion] = load_questions(QUESTIONS)
    combined = load_questions(QUESTIONS_150)
    assert set(combined[0].model_dump()) == set(seeded[0].model_dump())
