from datetime import date
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.contracts import (
    Answer,
    Citation,
    CitationResolution,
    Device,
    DeviceType,
    DeviceVersion,
    IndexReport,
    InsufficientEvidence,
    InvalidCitation,
    ModelFormatError,
    QueryFacts,
    QueryPlan,
    RetrievedDevice,
    VerificationResult,
    VigenciaStatus,
)


def make_device(**overrides):
    data = {
        "id": "lmp/art22",
        "norm_id": "lmp",
        "parent_id": None,
        "artigo_id": "lmp/art22",
        "tipo": "artigo",
        "rotulo": "Art. 22",
        "caminho": "Título III > Capítulo II > Art. 22",
        "ordem": 1,
    }
    data.update(overrides)
    return Device(**data)


def make_facts(**overrides):
    data = {
        "relacao": "companheiro",
        "tipo_violencia": ["fisica", "psicologica"],
        "urgencia": "recente",
        "data_fato": date(2026, 1, 2),
        "uf": "SP",
    }
    data.update(overrides)
    return QueryFacts(**data)


def test_literal_values() -> None:
    assert get_args(DeviceType) == ("artigo", "caput", "paragrafo", "inciso", "alinea", "item")
    assert get_args(VigenciaStatus) == (
        "vigente",
        "alterado",
        "revogado",
        "cancelado",
        "superado",
    )


def test_device_contract() -> None:
    device = make_device()
    assert device.parent_id is None
    assert make_device(parent_id="lmp/art22/cpt", tipo="caput").parent_id == "lmp/art22/cpt"

    with pytest.raises(ValidationError):
        make_device(tipo="paragrafo_unico")
    with pytest.raises(ValidationError):
        Device.model_validate({"id": "x", "norm_id": "lmp"})


def test_device_version_contract() -> None:
    version = DeviceVersion(
        device_id="lmp/art22",
        norm_version_id=42,
        texto_literal="texto",
        texto_anterior=None,
        contexto="contexto",
        citacao="Lei nº 11.340/2006, art. 22",
        vigencia_status="vigente",
        redacao_dada_por=None,
        vigencia_inicio=date(2006, 9, 22),
        vigencia_fim=None,
        fonte_url="https://example.test/lmp",
        content_hash="abc",
        qdrant_point_id=uuid4(),
        search_text="texto",
    )
    assert version.vigencia_fim is None
    with pytest.raises(ValidationError):
        DeviceVersion.model_validate({**version.model_dump(), "vigencia_status": "em_vigor"})


def test_retrieved_and_citation_contracts() -> None:
    retrieved = RetrievedDevice(
        device_id="lmp/art22",
        norm_version_id=42,
        score=0.9,
        source="dense",
        texto_literal="texto",
        citacao="citação",
    )
    assert retrieved.source == "dense"

    citation = Citation(
        device_id="lmp/art22",
        norm_version_id=42,
        citacao="citação",
        texto="texto",
        contexto="contexto",
        vigencia="vigente",
        fonte_url="https://example.test",
    )
    assert citation.vigencia == "vigente"

    with pytest.raises(ValidationError):
        RetrievedDevice(
            device_id="x",
            norm_version_id=1,
            score=0.1,
            source="fts",
            texto_literal="t",
            citacao="c",
        )


def test_query_facts_contract() -> None:
    facts = make_facts()
    assert facts.tipo_violencia == ["fisica", "psicologica"]

    with pytest.raises(ValidationError):
        make_facts(relacao="amigo")
    with pytest.raises(ValidationError):
        make_facts(tipo_violencia=["financeira"])


def test_answer_contract() -> None:
    answer = Answer(
        resposta="resposta",
        citacoes=[],
        proximos_passos=["procurar a delegacia"],
        encaminhamentos=[{"nome": "DEAM"}],
        premissas=["premissa"],
        nivel_confianca="medio",
        abstencao=False,
        motivo_abstencao=None,
    )
    assert answer.nivel_confianca == "medio"

    with pytest.raises(ValidationError):
        Answer(
            resposta="r",
            citacoes=[],
            proximos_passos=[],
            encaminhamentos=[],
            premissas=[],
            nivel_confianca="altissimo",
            abstencao=True,
            motivo_abstencao=None,
        )


def test_index_report_contract() -> None:
    report = IndexReport(path="fallback", indexed=3, model="harrier-oss-v1-0.6b")
    assert report.skipped == 0
    assert report.errors == []
    assert report.model_revision is None

    with pytest.raises(ValidationError):
        IndexReport(path="cpu", indexed=1, model="m")


def test_citation_resolution_contract() -> None:
    resolution = CitationResolution(resolved=True, device_id="lmp/art22", norm_id="lmp")
    assert resolution.artigo_id is None
    assert resolution.ambiguous is False
    assert resolution.reason is None


def test_query_plan_enforces_max_three_subquestions() -> None:
    plan = QueryPlan(
        fatos=make_facts(),
        consulta_juridica="consulta",
        subperguntas=["a", "b", "c"],
    )
    assert len(plan.subperguntas) == 3

    with pytest.raises(ValidationError):
        QueryPlan(
            fatos=make_facts(),
            consulta_juridica="consulta",
            subperguntas=["a", "b", "c", "d"],
        )


def test_verification_result_contract() -> None:
    result = VerificationResult(ok=True, deterministic_ok=True, action="accept")
    assert result.semantic_ok is None
    assert result.issues == []

    with pytest.raises(ValidationError):
        VerificationResult(ok=False, deterministic_ok=True, action="retry")


def test_exceptions() -> None:
    for exc_type in (ModelFormatError, InvalidCitation, InsufficientEvidence):
        assert issubclass(exc_type, Exception)
        with pytest.raises(exc_type):
            raise exc_type("boom")
