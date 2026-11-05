"""Pydantic request/response models for the HTTP API (GEN-05)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.contracts import Answer, Citation, QueryFacts, VigenciaStatus

LEGAL_NOTICE_PREFIX = (
    "Esta é uma orientação informativa e não substitui atendimento jurídico individual."
)


def legal_notice(data_atualizacao_base: str | None) -> str:
    data = data_atualizacao_base or "data não informada"
    return (
        f"{LEGAL_NOTICE_PREFIX}\n"
        f"A base foi atualizada em {data}. Se você está em perigo, ligue 190."
    )


class ChatFacts(BaseModel):
    """Facts accepted from the client; the rest is inferred by the pipeline."""

    model_config = ConfigDict(extra="forbid")

    data_fato: date | None = None
    uf: str | None = Field(default=None, min_length=2, max_length=2)

    def to_query_facts(self) -> QueryFacts:
        return QueryFacts(
            relacao="desconhecido",
            tipo_violencia=[],
            urgencia="desconhecida",
            data_fato=self.data_fato,
            uf=self.uf.upper() if self.uf else None,
        )


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    facts: ChatFacts | None = None

    def query_facts(self) -> QueryFacts | None:
        return self.facts.to_query_facts() if self.facts is not None else None


class CitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    norm_version_id: int
    citacao: str
    texto: str
    contexto: str = ""
    vigencia: VigenciaStatus
    fonte_url: str

    @classmethod
    def from_citation(cls, citation: Citation) -> CitationResponse:
        return cls(**citation.model_dump())


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resposta: str
    citacoes: list[CitationResponse]
    proximos_passos: list[str]
    encaminhamentos: list[dict]
    premissas: list[str]
    nivel_confianca: Literal["alto", "medio", "baixo"]
    abstencao: bool
    motivo_abstencao: str | None
    emergencia: bool
    data_atualizacao_base: str | None
    aviso_legal: str

    @classmethod
    def from_answer(
        cls,
        answer: Answer,
        *,
        emergencia: bool,
        data_atualizacao_base: str | None,
    ) -> ChatResponse:
        return cls(
            resposta=answer.resposta,
            citacoes=[CitationResponse.from_citation(item) for item in answer.citacoes],
            proximos_passos=list(answer.proximos_passos),
            encaminhamentos=[dict(item) for item in answer.encaminhamentos],
            premissas=list(answer.premissas),
            nivel_confianca=answer.nivel_confianca,
            abstencao=answer.abstencao,
            motivo_abstencao=answer.motivo_abstencao,
            emergencia=emergencia,
            data_atualizacao_base=data_atualizacao_base,
            aviso_legal=legal_notice(data_atualizacao_base),
        )


class SourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    norm_version_id: int
    norm_id: str | None = None
    artigo_id: str | None = None
    citacao: str
    texto_literal: str
    contexto: str
    vigencia: VigenciaStatus
    vigencia_inicio: date | None = None
    vigencia_fim: date | None = None
    fonte_url: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    database: str
    qdrant: str
    index_version: str | None = None
    last_ingest: str | None = None
    data_atualizacao_base: str | None = None
