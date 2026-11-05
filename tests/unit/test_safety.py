import inspect

import pytest

from src.contracts import Answer
from src.safety.risk import (
    EMERGENCY_BLOCK,
    RiskAssessment,
    classify_risk,
    emergency_answer,
)

DOCS_08_EMERGENCY = [
    "Ele está aqui e está me batendo.",
    "Ele disse que vai me matar hoje.",
    "Estou trancada dentro de casa.",
    "Ele está me seguindo agora.",
    "Meu filho está sendo agredido.",
]

EXPECTED_BLOCK = """\
Se você está em perigo agora, ligue 190 (Polícia).
Se puder, vá para um local seguro e procure uma pessoa de confiança.
Não confronte o agressor.

A Central de Atendimento à Mulher é o 180 (24 horas).
Direitos Humanos: 100.
Polícia Civil: 197.

Você quer que eu te explique os direitos e os próximos passos depois?"""


@pytest.mark.parametrize("phrase", DOCS_08_EMERGENCY)
def test_docs_08_emergency_phrases_are_immediate(phrase: str) -> None:
    assessment = classify_risk(phrase)

    assert assessment.immediate is True
    assert assessment.signals


def test_emergency_block_matches_docs_text() -> None:
    assert EMERGENCY_BLOCK == EXPECTED_BLOCK
    assert "190" in EMERGENCY_BLOCK
    assert "180" in EMERGENCY_BLOCK
    assert "100" in EMERGENCY_BLOCK
    assert "197" in EMERGENCY_BLOCK
    assert "vai chegar" not in EMERGENCY_BLOCK.lower()
    assert "endereço" not in EMERGENCY_BLOCK.lower()


def test_historical_aggression_is_not_immediate() -> None:
    assessment = classify_risk("Ele me bateu há dois anos.")

    assert assessment.immediate is False
    assert assessment.signals == ["historical"]


def test_historical_threat_is_not_immediate() -> None:
    assessment = classify_risk("Ele me ameaçou no passado.")

    assert assessment.immediate is False
    assert assessment.signals == ["historical"]


@pytest.mark.parametrize(
    "phrase",
    [
        "ELE ESTÁ ME BATENDO",
        "ele esta me batendo",
        "Ele está com faca",
        "Ele está com arma",
        "Ele não me deixa sair",
        "Ele trancou a porta",
        "Ele está me perseguindo",
        "Ele me forçou",
        "Ele me estuprou",
        "Não quero mais viver",
        "Vou me matar",
        "Ele está machucando meu filho",
    ],
)
def test_accent_case_and_signal_variants(phrase: str) -> None:
    assert classify_risk(phrase).immediate is True


def test_benign_question_is_not_immediate() -> None:
    assessment = classify_risk("Como pedir uma medida protetiva?")

    assert assessment.immediate is False
    assert assessment.signals == []
    assert assessment.kind is None


def test_assessment_contract() -> None:
    assessment = RiskAssessment(immediate=True, signals=["agressao"], kind="agressao")

    assert assessment.immediate is True
    assert assessment.kind == "agressao"


def test_emergency_answer_needs_no_retrieval_input() -> None:
    signature = inspect.signature(emergency_answer)
    assert list(signature.parameters) == []

    answer = emergency_answer()

    assert isinstance(answer, Answer)
    assert answer.abstencao is False
    assert answer.motivo_abstencao is None
    assert answer.nivel_confianca == "alto"
    assert answer.citacoes == []
    assert "190" in answer.resposta
    assert any("180" in step for step in answer.proximos_passos)
    assert any("DEAM" in step for step in answer.proximos_passos)
    assert any("Defensoria" in step for step in answer.proximos_passos)
