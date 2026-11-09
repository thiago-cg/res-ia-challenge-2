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
        "Ele me ameaçou de me matar há dois anos.",
        "Ele me estuprou há dois anos.",
        "Ele me ameaçou de me matar anos atrás.",
        "Ele me estuprou no passado.",
        "Ele me ameaçou de me matar ontem.",
        "Ele me estuprou há 3 dias.",
        "Ele me bateu há duas semanas.",
        "Ele me agrediu dias atrás.",
    ],
)
def test_remote_threat_and_sexual_violence_are_not_immediate(phrase: str) -> None:
    assessment = classify_risk(phrase)

    assert assessment.immediate is False
    assert assessment.signals == ["historical"]


@pytest.mark.parametrize(
    "phrase",
    [
        "Ele está me ameaçando de me matar agora.",
        "Ele está me estuprando agora.",
    ],
)
def test_present_threat_and_sexual_violence_are_immediate(phrase: str) -> None:
    assessment = classify_risk(phrase)

    assert assessment.immediate is True
    assert assessment.signals


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


# The phrase table used to list literal strings, so it only fired when the
# message reproduced the exact pronoun and article ("esta com arma", "esta me
# agredindo").  Real messages vary the surface form, and the evaluation set
# showed 5 of 20 emergency questions slipping through into the normal answer
# path.
@pytest.mark.parametrize(
    "phrase",
    [
        "Ele acabou de me empurrar e está gritando comigo.",
        "Ele está quebrando tudo e me ameaçando agora.",
        "Ele está com uma arma e está na minha frente.",
        "Estou escondida no banheiro e ele está batendo na porta.",
        "Meu companheiro está agredindo minha mãe neste momento.",
        "Ele está com um revólver na mão.",
    ],
)
def test_imminent_variants_that_are_not_literal_phrases_are_immediate(phrase: str) -> None:
    assert classify_risk(phrase).immediate is True


# The other half of the same problem: widening the table must not turn a
# historical report, or a question about a past event, into an emergency.  The
# normal answer path is the correct one for these.
@pytest.mark.parametrize(
    "phrase",
    [
        "Ele me agrediu e eu não sei se ainda dá tempo de denunciar.",
        "Ele me empurrou e me ameaçou, mas só agora consegui pedir ajuda.",
        "Ele me bateu e sumiu, ainda posso fazer alguma coisa.",
        "Meu companheiro me agrediu e eu não registrei nada na época.",
        "Ele fica me ameaçando e dizendo que eu não valho nada.",
        "Ele me ameaçou, isso é crime.",
    ],
)
def test_past_reports_and_legal_questions_are_not_immediate(phrase: str) -> None:
    assert classify_risk(phrase).immediate is False
