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
        "fonte_url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
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
    assert insufficient_evidence([make_retrieved(score=0.01)]) is False
    assert MIN_SCORE == 0.0


def test_explicit_device_is_never_abstained_on_score() -> None:
    explicit = make_retrieved(score=0.0, source="explicit")

    assert insufficient_evidence([explicit]) is False
    assert insufficient_evidence([explicit], min_score=0.9) is False

    answer = build_safe_answer([explicit], "falha", min_score=0.9)
    assert len(answer.citacoes) == 1


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
    assert answer.citacoes[0].fonte_url == (
        "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"
    )
    assert "dispositivos recuperados" in answer.resposta.lower()
    assert any("Defensoria" in step for step in answer.proximos_passos)


def test_build_safe_answer_never_invents_citation() -> None:
    answer = build_safe_answer([make_retrieved("lmp/art22", 0.9)], "falha")

    assert {citation.device_id for citation in answer.citacoes} == {"lmp/art22"}


@pytest.mark.parametrize("score", [0.01, 0.5, 1.0])
def test_build_safe_answer_accepts_scores_above_threshold(score: float) -> None:
    answer = build_safe_answer([make_retrieved(score=score)], "falha")

    assert len(answer.citacoes) == 1


def test_build_safe_answer_abstains_on_non_explicit_zero_score() -> None:
    answer = build_safe_answer([make_retrieved(score=0.0)], "sem evidência")

    assert answer.abstencao is True
    assert answer.citacoes == []


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


def test_dedupe_keeps_highest_score_per_artigo_id() -> None:
    answer = build_safe_answer(
        [
            make_retrieved("lmp/art22/cpt/inc3/ali-b", 0.3),
            make_retrieved("lmp/art24", 0.9),
            make_retrieved("lmp/art22/cpt/inc3/ali-c", 0.8),
        ],
        "falha",
    )

    by_artigo = {citation.device_id: citation for citation in answer.citacoes}
    assert "lmp/art22/cpt/inc3/ali-c" in by_artigo
    assert "lmp/art22/cpt/inc3/ali-b" not in by_artigo
    assert [citation.device_id for citation in answer.citacoes] == [
        "lmp/art24",
        "lmp/art22/cpt/inc3/ali-c",
    ]


def test_no_silent_citation_loss_for_known_and_unknown_vigencia() -> None:
    known = make_retrieved("lmp/art22", 0.9, vigencia="vigente")
    unknown = make_retrieved("lmp/art24", 0.8, vigencia=None)

    answer = build_safe_answer([known, unknown], "falha")

    assert [citation.device_id for citation in answer.citacoes] == ["lmp/art22"]
    assert all(citation.device_id != "lmp/art24" for citation in answer.citacoes)
    assert "lmp/art24" in answer.resposta
    assert "vigência não verificada" in answer.resposta
    assert any(
        "Vigência não verificada" in premise and "lmp/art24" in premise
        for premise in answer.premissas
    )


def test_cross_source_dedupe_keeps_citable_duplicate() -> None:
    explicit = make_retrieved("lmp/art22/cpt/inc3/ali-b", 0.0, source="explicit", vigencia=None)
    known = make_retrieved("lmp/art22/cpt/inc3/ali-c", 0.9, vigencia="vigente")

    answer = build_safe_answer([explicit, known], "falha")

    assert len(answer.citacoes) == 1
    assert answer.citacoes[0].device_id == "lmp/art22/cpt/inc3/ali-c"
    assert answer.citacoes[0].vigencia == "vigente"
    assert "vigência não verificada" not in answer.resposta


def test_cross_source_dedupe_prefers_known_explicit_without_duplicate() -> None:
    explicit = make_retrieved(
        "lmp/art22/cpt/inc3/ali-b", 0.0, source="explicit", vigencia="vigente"
    )
    unknown = make_retrieved("lmp/art22/cpt/inc3/ali-c", 0.9, vigencia=None)

    answer = build_safe_answer([explicit, unknown], "falha")

    assert [citation.device_id for citation in answer.citacoes] == ["lmp/art22/cpt/inc3/ali-b"]
    assert "vigência não verificada" not in answer.resposta


def test_explicit_devices_are_included_before_score_cap() -> None:
    non_explicit = [make_retrieved(f"lmp/art{index}", 0.9) for index in range(1, 11)]
    explicit = make_retrieved("lmp/explicit", 0.0, source="explicit")

    answer = build_safe_answer(non_explicit + [explicit], "falha")

    assert len(answer.citacoes) == 10
    assert answer.citacoes[0].device_id == "lmp/explicit"
    assert "lmp/explicit" not in {citation.device_id for citation in answer.citacoes[1:]}


def test_dedupe_prefers_known_vigencia_over_higher_score() -> None:
    answer = build_safe_answer(
        [
            make_retrieved("lmp/art22/cpt/inc3/ali-b", 0.9, vigencia=None),
            make_retrieved("lmp/art22/cpt/inc3/ali-c", 0.8, vigencia="vigente"),
        ],
        "falha",
    )

    assert [citation.device_id for citation in answer.citacoes] == ["lmp/art22/cpt/inc3/ali-c"]
    assert answer.citacoes[0].vigencia == "vigente"


def test_build_safe_answer_caps_citations() -> None:
    retrieved = [make_retrieved(f"lmp/art{index}", 0.9) for index in range(1, 15)]

    answer = build_safe_answer(retrieved, "falha")

    assert len(answer.citacoes) == 10
