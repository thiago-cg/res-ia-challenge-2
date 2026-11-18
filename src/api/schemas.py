"""Pydantic request/response models for the HTTP API (GEN-05)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    #: Ask for the multi-agent execution trail in the response (no user text in it).
    trace: bool = False

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
    afirmacao: str = ""

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
    trace: list[dict] | None = None

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
    capabilities: dict[str, bool] = Field(default_factory=dict)


ServiceTipo = Literal["deam", "nucleo_atendimento_mulher", "delegacia_comum"]


class NearbyRequest(BaseModel):
    """Where to look: coordinates (nearest first) or, without them, a municipality.

    Sent as a POST body, never as a query string, so coordinates stay out of access logs.
    """

    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    municipio: str | None = Field(default=None, min_length=1, max_length=120)
    tipo: ServiceTipo | None = None
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _needs_a_place(self) -> NearbyRequest:
        has_point = self.lat is not None and self.lon is not None
        half_point = (self.lat is None) != (self.lon is None)
        has_city = bool(self.uf and self.municipio)
        if half_point or not (has_point or has_city):
            raise ValueError("informe lat e lon, ou uf e municipio")
        return self


class ServiceOut(BaseModel):
    nome: str
    tipo: ServiceTipo
    uf: str
    municipio: str
    endereco: str | None
    telefone: str | None
    horario: str | None
    latitude: float
    longitude: float
    #: Distance in km from the given point; null when searching by municipality.
    distancia_km: float | None
    fonte_url: str
    atualizado_em: date
    #: false = the point on the map is approximate and still has to be conferred.
    coordenada_verificada: bool


class ReferenciaOut(BaseModel):
    """Ponto de partida das distâncias quando a busca foi por cidade (centro da cidade)."""

    latitude: float
    longitude: float
    rotulo: str


class NearbyResponse(BaseModel):
    servicos: list[ServiceOut]
    referencia: ReferenciaOut | None = None
    deam_mais_proxima: ServiceOut | None
    aviso: str | None
    emergencia: dict[str, str] = {"policia_militar": "190", "central_mulher": "180"}
    aviso_legal: str = (
        "Confirme o endereço e o horário por telefone antes de ir. Em perigo imediato, ligue 190."
    )
