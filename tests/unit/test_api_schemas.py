from datetime import date

import pytest
from pydantic import ValidationError

from src.api.schemas import (
    LEGAL_NOTICE_PREFIX,
    ChatFacts,
    ChatRequest,
    ChatResponse,
    CitationResponse,
    HealthResponse,
    SourceResponse,
    legal_notice,
)
from src.contracts import Answer, Citation


def make_answer(**overrides) -> Answer:
    data = {
        "resposta": "Resposta de teste.",
        "citacoes": [],
        "proximos_passos": ["Procurar a Defensoria Pública."],
        "encaminhamentos": [{"tipo": "defensoria", "descricao": "Orientação."}],
        "premissas": [],
        "nivel_confianca": "medio",
        "abstencao": False,
        "motivo_abstencao": None,
    }
    data.update(overrides)
    return Answer(**data)


def make_citation(**overrides) -> Citation:
    data = {
        "device_id": "lmp/art22",
        "norm_version_id": 7,
        "citacao": "Lei nº 11.340/2006, art. 22",
        "texto": "Texto literal.",
        "contexto": "Contexto.",
        "vigencia": "vigente",
        "fonte_url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
    }
    data.update(overrides)
    return Citation(**data)


def test_chat_request_accepts_optional_facts() -> None:
    request = ChatRequest(
        session_id="session-1",
        message="Como pedir medida protetiva?",
        facts={"data_fato": "2026-10-01", "uf": "sp"},
    )

    facts = request.query_facts()
    assert facts is not None
    assert facts.data_fato == date(2026, 10, 1)
    assert facts.uf == "SP"
    assert facts.relacao == "desconhecido"
    assert facts.urgencia == "desconhecida"


def test_chat_request_without_facts_returns_none() -> None:
    request = ChatRequest(session_id="session-1", message="Quero ajuda")

    assert request.query_facts() is None


@pytest.mark.parametrize("field", ["norm_version_id", "device_id", "extras"])
def test_chat_request_forbids_extra_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "session_id": "session-1",
                "message": "Pergunta",
                field: "valor",
            }
        )


def test_chat_request_requires_session_id_and_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(session_id="", message="Pergunta")
    with pytest.raises(ValidationError):
        ChatRequest(session_id="session-1", message="")


def test_chat_facts_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ChatFacts.model_validate({"data_fato": "2026-10-01", "relacao": "companheiro"})


def test_chat_facts_uf_must_have_two_letters() -> None:
    with pytest.raises(ValidationError):
        ChatFacts(uf="S")


def test_citation_response_from_citation() -> None:
    response = CitationResponse.from_citation(make_citation())

    assert response.device_id == "lmp/art22"
    assert response.norm_version_id == 7
    assert response.vigencia == "vigente"


def test_chat_response_includes_emergency_and_base_date() -> None:
    response = ChatResponse.from_answer(
        make_answer(citacoes=[make_citation()]),
        emergencia=True,
        data_atualizacao_base="2026-11-05",
    )

    assert response.emergencia is True
    assert response.data_atualizacao_base == "2026-11-05"
    assert response.citacoes[0].device_id == "lmp/art22"
    assert response.aviso_legal.startswith(LEGAL_NOTICE_PREFIX)
    assert "2026-11-05" in response.aviso_legal
    assert "190" in response.aviso_legal


def test_chat_response_allows_missing_base_date() -> None:
    response = ChatResponse.from_answer(
        make_answer(),
        emergencia=False,
        data_atualizacao_base=None,
    )

    assert response.data_atualizacao_base is None
    assert "data não informada" in response.aviso_legal


def test_chat_response_requires_emergencia() -> None:
    payload = ChatResponse.from_answer(
        make_answer(),
        emergencia=False,
        data_atualizacao_base=None,
    ).model_dump()
    payload.pop("emergencia")

    with pytest.raises(ValidationError):
        ChatResponse.model_validate(payload)


def test_legal_notice_is_permanent_and_cites_190() -> None:
    notice = legal_notice("2026-11-05")

    assert LEGAL_NOTICE_PREFIX in notice
    assert "não substitui atendimento jurídico individual" in notice
    assert "A base foi atualizada em 2026-11-05." in notice
    assert "ligue 190" in notice


def test_source_response_contract() -> None:
    response = SourceResponse(
        device_id="lmp/art22",
        norm_version_id=7,
        norm_id="lmp",
        artigo_id="lmp/art22",
        citacao="Lei nº 11.340/2006, art. 22",
        texto_literal="Texto literal.",
        contexto="Contexto.",
        vigencia="alterado",
        vigencia_inicio=date(2006, 8, 7),
        vigencia_fim=None,
        fonte_url="https://example.test/lmp",
    )

    assert response.vigencia == "alterado"
    assert response.vigencia_inicio == date(2006, 8, 7)


def test_source_response_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SourceResponse.model_validate(
            {
                "device_id": "lmp/art22",
                "norm_version_id": 7,
                "citacao": "Lei",
                "texto_literal": "Texto",
                "contexto": "",
                "vigencia": "vigente",
                "fonte_url": "https://example.test",
                "extra": "não permitido",
            }
        )


def test_health_response_status_is_strict() -> None:
    with pytest.raises(ValidationError):
        HealthResponse(status="broken", database="ok", qdrant="ok")
