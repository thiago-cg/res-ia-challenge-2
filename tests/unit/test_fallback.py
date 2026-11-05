import pytest

from src.contracts import Answer, RetrievedDevice
from src.generate.fallback import (
    MIN_SCORE,
    abstain,
    build_safe_answer,
    insufficient_evidence,
)


def make_retrieved(
    device_id: str = "lmp/art22", score: float = 0.8, **overrides
) -> RetrievedDevice:
    data = {
        "device_id": device_id,
        "norm_version_id": 42,
        "score": score,
        "source": "dense",
        "texto_literal": "Texto literal do dispositivo.",
        "citacao": "Lei nº 11.340/2006, art. 22",
        "vigencia": "vigente",
    }
    data.update(overrides)
    return RetrievedDevice(**data)


def test_abstain_outside_corpus() -> None:
    answer = abstain("fora do corpus")

    assert isinstance(answer, Answer)
    assert answer.abstencao is True
    assert answer.motivo_abstencao == "fora do corpus"
    assert answer.nivel_confianca == "baixo"
    assert answer.citacoes == []
    assert "Não encontrei base suficiente" in answer.resposta
    assert any("Defensoria" in step for step in answer.proximos_passos)
    assert any("180" in step for step in answer.proximos_passos)
    assert any("DEAM" in step for step in answer.proximos_passos)
    assert {item["tipo"] for item in answer.encaminhamentos} == {
        "defensoria",
        "central_mulher",
        "deam",
    }


def test_abstain_with_retrieved_does_not_invent_citations() -> None:
    answer = abstain("data ausente", retrieved=[make_retrieved()])

    assert answer.abstencao is True
    assert answer.citacoes == []


def test_abstain_includes_update_date() -> None:
    answer = abstain("base antiga", data_atualizacao="01/10/2026")

    assert "01/10/2026" in answer.resposta


def test_insufficient_evidence_without_retrieval() -> None:
    assert insufficient_evidence(None) is True
    assert insufficient_evidence([]) is True


def test_insufficient_evidence_with_low_score() -> None:
    assert insufficient_evidence([make_retrieved(score=-0.1)]) is True
    assert insufficient_evidence([make_retrieved(score=0.0)]) is True
    assert MIN_SCORE > 0.0


def test_insufficient_evidence_threshold_is_injectable() -> None:
    retrieved = [make_retrieved(score=0.3)]

    assert insufficient_evidence(retrieved, min_score=0.5) is True
    assert insufficient_evidence(retrieved, min_score=0.2) is False


def test_sufficient_evidence_passes() -> None:
    assert insufficient_evidence([make_retrieved(score=0.8)]) is False


def test_build_safe_answer_without_retrieval_abstains() -> None:
    answer = build_safe_answer([], "sem evidência")

    assert answer.abstencao is True
    assert answer.motivo_abstencao == "sem evidência"
    assert answer.citacoes == []


def test_build_safe_answer_with_low_score_abstains() -> None:
    answer = build_safe_answer([make_retrieved(score=-0.5)], "score baixo")

    assert answer.abstencao is True
    assert answer.citacoes == []


def test_build_safe_answer_shows_retrieved_devices_when_generation_fails() -> None:
    retrieved = [
        make_retrieved("lmp/art22", 0.9),
        make_retrieved("lmp/art24", 0.7),
    ]

    answer = build_safe_answer(retrieved, "geração falhou")

    assert answer.abstencao is True
    assert answer.motivo_abstencao == "geração falhou"
    assert [citation.device_id for citation in answer.citacoes] == ["lmp/art22", "lmp/art24"]
    assert [citation.norm_version_id for citation in answer.citacoes] == [42, 42]
    assert answer.citacoes[0].texto == "Texto literal do dispositivo."
    assert "dispositivos recuperados" in answer.resposta.lower()
    assert any("Defensoria" in step for step in answer.proximos_passos)


def test_build_safe_answer_never_invents_citation() -> None:
    answer = build_safe_answer([make_retrieved("lmp/art22", 0.9)], "falha")

    assert {citation.device_id for citation in answer.citacoes} == {"lmp/art22"}


@pytest.mark.parametrize("score", [MIN_SCORE, 0.5, 1.0])
def test_build_safe_answer_accepts_scores_at_or_above_threshold(score: float) -> None:
    answer = build_safe_answer([make_retrieved(score=score)], "falha")

    assert len(answer.citacoes) == 1


def test_build_safe_answer_does_not_fabricate_vigencia() -> None:
    answer = build_safe_answer(
        [make_retrieved("lmp/art22", 0.9, vigencia=None)],
        "falha",
    )

    assert answer.citacoes == []
    assert "vigência não verificada" in answer.resposta
    assert "Texto literal do dispositivo." in answer.resposta
    assert any("Vigência não verificada" in premise for premise in answer.premissas)


def test_build_safe_answer_uses_known_vigencia() -> None:
    answer = build_safe_answer(
        [make_retrieved("lmp/art22", 0.9, vigencia="alterado")],
        "falha",
    )

    assert answer.citacoes[0].vigencia == "alterado"


def test_build_safe_answer_dedupes_by_artigo_id() -> None:
    answer = build_safe_answer(
        [
            make_retrieved("lmp/art22/cpt/inc3/ali-b", 0.9),
            make_retrieved("lmp/art22/cpt/inc3/ali-c", 0.8),
            make_retrieved("lmp/art24", 0.7),
        ],
        "falha",
    )

    assert [citation.device_id for citation in answer.citacoes] == [
        "lmp/art22/cpt/inc3/ali-b",
        "lmp/art24",
    ]


def test_build_safe_answer_caps_citations() -> None:
    retrieved = [make_retrieved(f"lmp/art{index}", 0.9) for index in range(1, 15)]

    answer = build_safe_answer(retrieved, "falha")

    assert len(answer.citacoes) == 10
