from __future__ import annotations

import pytest

from src.contracts import Answer, Citation, RetrievedDevice
from src.generate.verify import verify


class FakeRepo:
    def __init__(self, rows: dict[tuple[str, int], dict] | None = None) -> None:
        self.rows = rows or {}

    def get_device_version(self, device_id: str, norm_version_id: int) -> dict | None:
        return self.rows.get((device_id, norm_version_id))


def row(texto: str = "contato com a ofendida", citacao: str | None = None) -> dict:
    return {
        "norm_version_id": 1,
        "texto_literal": texto,
        "citacao": citacao or "Lei nº 11.340/2006, art. 22, inciso III",
        "contexto": "Art. 22",
        "vigencia_status": "vigente",
        "fonte_url": "https://www.planalto.gov.br",
    }


def retrieved(
    device_id: str = "lmp/art22",
    version: int = 1,
    texto: str = "contato com a ofendida",
) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=version,
        score=0.9,
        source="maxsim",
        texto_literal=texto,
        citacao="Lei nº 11.340/2006, art. 22, inciso III",
        vigencia="vigente",
    )


def citation(
    device_id: str = "lmp/art22",
    version: int = 1,
    citacao: str = "Lei nº 11.340/2006, art. 22, inciso III",
    texto: str = "contato com a ofendida",
) -> Citation:
    return Citation(
        device_id=device_id,
        norm_version_id=version,
        citacao=citacao,
        texto=texto,
        contexto="Art. 22",
        vigencia="vigente",
        fonte_url="https://www.planalto.gov.br",
    )


def answer(
    resposta: str = "A lei permite requerer medida protetiva.",
    citacoes: list[Citation] | None = None,
    *,
    abstencao: bool = False,
) -> Answer:
    return Answer(
        resposta=resposta,
        citacoes=citacoes if citacoes is not None else [citation()],
        proximos_passos=["Procurar a Defensoria Pública."],
        encaminhamentos=[],
        premissas=[],
        nivel_confianca="medio",
        abstencao=abstencao,
        motivo_abstencao=None,
    )


def test_clean_answer_is_accepted() -> None:
    result = verify(
        answer(),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is True
    assert result.deterministic_ok is True
    assert result.semantic_ok is None
    assert result.issues == []
    assert result.action == "accept"


def test_unknown_citation_id_is_rejected() -> None:
    result = verify(
        answer(citacoes=[citation(device_id="lmp/inventado")]),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is False
    assert result.deterministic_ok is False
    assert result.action == "regenerate"
    assert any("inventado" in issue for issue in result.issues)


def test_citation_not_in_retrieved_set_is_rejected() -> None:
    result = verify(
        answer(citacoes=[citation(device_id="lmp/art24")]),
        [retrieved()],
        repo=FakeRepo(
            {
                ("lmp/art22", 1): row(),
                ("lmp/art24", 1): row(texto="outro texto"),
            }
        ),
    )

    assert result.ok is False
    assert any("not retrieved" in issue for issue in result.issues)


def test_version_mismatch_is_rejected() -> None:
    result = verify(
        answer(citacoes=[citation(version=2)]),
        [retrieved()],
        repo=FakeRepo(
            {
                ("lmp/art22", 1): row(),
                ("lmp/art22", 2): row(texto="texto da versão 2"),
            }
        ),
    )

    assert result.ok is False
    assert any("version" in issue for issue in result.issues)


def test_citation_metadata_mismatch_is_rejected() -> None:
    result = verify(
        answer(citacoes=[citation(citacao="Lei nº 11.340/2006, art. 99")]),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is False
    assert any("metadata" in issue for issue in result.issues)


def test_quoted_text_outside_literal_is_rejected() -> None:
    result = verify(
        answer(resposta='A lei diz que "o agressor será preso em 24 horas" sempre.'),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is False
    assert any("quoted" in issue for issue in result.issues)


def test_quote_inside_literal_is_accepted() -> None:
    result = verify(
        answer(resposta='O texto fala em "contato com a ofendida".'),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is True


def test_legal_claim_without_citation_is_rejected() -> None:
    result = verify(
        answer(resposta="A lei garante medida protetiva em todos os casos.", citacoes=[]),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is False
    assert any("citation" in issue for issue in result.issues)


def test_abstention_without_citation_is_accepted() -> None:
    result = verify(
        answer(resposta="Não há base suficiente.", citacoes=[], abstencao=True),
        [],
    )

    assert result.ok is True


def test_judge_unsupported_claim_triggers_regenerate() -> None:
    result = verify(
        answer(),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
        judge=lambda answer, retrieved: ["claim not supported by device"],
    )

    assert result.ok is False
    assert result.deterministic_ok is True
    assert result.semantic_ok is False
    assert result.action == "regenerate"


def test_persistent_failure_leads_to_abstain() -> None:
    result = verify(
        answer(),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
        judge=lambda answer, retrieved: ["promise of result"],
        attempt=2,
    )

    assert result.ok is False
    assert result.action == "abstain"


def test_judge_boolean_result_is_supported() -> None:
    result = verify(
        answer(),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
        judge=lambda answer, retrieved: True,
    )

    assert result.ok is True
    assert result.semantic_ok is True


def test_fabricated_citation_text_is_rejected() -> None:
    result = verify(
        answer(citacoes=[citation(texto="texto inventado")]),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is False
    assert any("not inside the hydrated literal" in issue for issue in result.issues)


def test_citation_text_matches_literal_after_whitespace_normalization() -> None:
    result = verify(
        answer(citacoes=[citation(texto="  contato   com a ofendida  ")]),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is True


def test_judge_body_type_error_propagates_without_retry() -> None:
    calls: list[int] = []

    def judge(answer: Answer, retrieved: list[RetrievedDevice]) -> list[str]:
        calls.append(1)
        raise TypeError("boom inside judge")

    with pytest.raises(TypeError, match="boom inside judge"):
        verify(
            answer(),
            [retrieved()],
            repo=FakeRepo({("lmp/art22", 1): row()}),
            judge=judge,
        )

    assert calls == [1]


def test_bracketed_citation_matches_hydrated_metadata() -> None:
    bracketed = "[Lei nº 11.340/2006, art. 22, inciso III]"
    result = verify(
        answer(citacoes=[citation(citacao=bracketed)]),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
    )

    assert result.ok is True


def test_judge_with_text_signature_receives_response_string() -> None:
    seen: dict[str, object] = {}

    def judge(resposta: str, retrieved: list[RetrievedDevice]) -> list[str]:
        seen["resposta"] = resposta
        return []

    result = verify(
        answer(resposta="A lei permite requerer medida protetiva."),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
        judge=judge,
    )

    assert result.ok is True
    assert seen["resposta"] == "A lei permite requerer medida protetiva."


def test_judge_with_answer_signature_receives_answer_object() -> None:
    seen: dict[str, object] = {}

    def judge(answer: Answer, retrieved: list[RetrievedDevice]) -> list[str]:
        seen["answer"] = answer
        return []

    result = verify(
        answer(),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
        judge=judge,
    )

    assert result.ok is True
    assert isinstance(seen["answer"], Answer)


def test_judge_with_one_text_parameter_receives_response_string() -> None:
    seen: dict[str, object] = {}

    def judge(resposta: str) -> list[str]:
        seen["resposta"] = resposta
        return []

    result = verify(
        answer(resposta="Texto da resposta."),
        [retrieved()],
        repo=FakeRepo({("lmp/art22", 1): row()}),
        judge=judge,
    )

    assert result.ok is True
    assert seen["resposta"] == "Texto da resposta."


def test_ambiguous_judge_signature_raises_before_calling() -> None:
    calls: list[int] = []

    def judge(thing: object, retrieved: list[RetrievedDevice]) -> list[str]:
        calls.append(1)
        return []

    with pytest.raises(TypeError, match="ambiguous judge signature"):
        verify(
            answer(),
            [retrieved()],
            repo=FakeRepo({("lmp/art22", 1): row()}),
            judge=judge,
        )

    assert calls == []
