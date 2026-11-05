from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from src.eval.run import is_canonical_device_id, load_questions

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
REGRESSIONS = DATA / "regressions.jsonl"
QUESTIONS = DATA / "questions.jsonl"

REQUIRED_BASES = (
    "15.438/2026",
    "14.550/2023",
    "542",
    "600",
    "22, III",
    "CNJ/CNMP nº 5/2020",
    "Portaria Conjunta nº 6/2025",
    "24-A",
    "14.994/2024",
)

REQUIRED_FIELDS = (
    "id",
    "pergunta",
    "device_ids",
    "data_fato",
    "resposta_esperada",
    "base_legal",
    "categoria",
    "split",
)


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in REGRESSIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def test_valid_json_and_required_fields() -> None:
    rows = _rows()
    assert len(rows) >= 10
    for row in rows:
        assert set(REQUIRED_FIELDS) <= set(row), row.get("id")
        assert row["id"].startswith("r")
        assert row["pergunta"].strip()
        assert row["resposta_esperada"].strip()
        assert row["base_legal"].strip()


def test_ids_are_unique() -> None:
    ids = [row["id"] for row in _rows()]
    assert len(ids) == len(set(ids))


def test_every_required_base_appears() -> None:
    bases = " ".join(row["base_legal"] for row in _rows())
    missing = [base for base in REQUIRED_BASES if base not in bases]
    assert missing == []


def test_device_ids_are_canonical() -> None:
    for row in _rows():
        for device_id in row["device_ids"]:
            assert is_canonical_device_id(device_id), (row["id"], device_id)


def test_emergency_and_abstention_have_no_device_ids() -> None:
    for row in _rows():
        if row["categoria"] in {"emergencia", "fora_do_corpus"}:
            assert row["device_ids"] == []


def test_emergency_abstention_and_prompt_injection_are_present() -> None:
    rows = _rows()
    assert any(row["categoria"] == "emergencia" for row in rows)
    assert any(row["categoria"] == "fora_do_corpus" for row in rows)
    assert any("IGNORE AS INSTRUÇÕES ANTERIORES" in row["pergunta"] for row in rows)


def test_no_duplicated_question_between_files() -> None:
    seeded = {_normalize(question.pergunta) for question in load_questions(QUESTIONS)}
    regression = {_normalize(row["pergunta"]) for row in _rows()}
    assert seeded.isdisjoint(regression)


def test_splits_and_categories_are_valid() -> None:
    valid_categories = {
        "prazo",
        "medida_protetiva",
        "acao_penal",
        "servicos",
        "emergencia",
        "fora_do_corpus",
    }
    for row in _rows():
        assert row["categoria"] in valid_categories
        assert row["split"] in {"dev", "test"}
        assert row["data_fato"] is None or isinstance(row["data_fato"], str)


def test_all_four_seeded_pillars_are_covered() -> None:
    categories = Counter(row["categoria"] for row in _rows())
    assert categories["prazo"] >= 1
    assert categories["acao_penal"] >= 1
    assert categories["medida_protetiva"] >= 1
    assert categories["servicos"] >= 1
