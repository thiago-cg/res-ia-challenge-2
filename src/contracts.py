from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DeviceType = Literal["artigo", "caput", "paragrafo", "inciso", "alinea", "item"]
VigenciaStatus = Literal["vigente", "alterado", "revogado", "cancelado", "superado"]


class Device(BaseModel):
    id: str
    norm_id: str
    parent_id: str | None
    artigo_id: str
    tipo: DeviceType
    rotulo: str
    caminho: str
    ordem: int


class DeviceVersion(BaseModel):
    device_id: str
    norm_version_id: int
    texto_literal: str
    texto_anterior: str | None
    contexto: str
    citacao: str
    vigencia_status: VigenciaStatus
    redacao_dada_por: str | None
    vigencia_inicio: date
    vigencia_fim: date | None
    fonte_url: str
    content_hash: str
    qdrant_point_id: UUID
    search_text: str


class RetrievedDevice(BaseModel):
    device_id: str
    norm_version_id: int
    score: float
    source: Literal["explicit", "bm25", "dense", "maxsim"]
    texto_literal: str
    citacao: str
    vigencia: VigenciaStatus | None = None
    contexto: str | None = None
    explicacao: str | None = None
    fonte_url: str | None = None


class QueryFacts(BaseModel):
    relacao: Literal["companheiro", "ex-companheiro", "familiar", "outro", "desconhecido"]
    tipo_violencia: list[
        Literal["fisica", "psicologica", "sexual", "patrimonial", "moral", "vicaria"]
    ]
    urgencia: Literal["imediata", "recente", "passada", "desconhecida"]
    data_fato: date | None
    uf: str | None


class Citation(BaseModel):
    device_id: str
    norm_version_id: int
    citacao: str
    texto: str
    contexto: str
    vigencia: VigenciaStatus
    fonte_url: str
    afirmacao: str = ""


class Answer(BaseModel):
    resposta: str
    citacoes: list[Citation]
    proximos_passos: list[str]
    encaminhamentos: list[dict]
    premissas: list[str]
    nivel_confianca: Literal["alto", "medio", "baixo"]
    abstencao: bool
    motivo_abstencao: str | None


class IndexReport(BaseModel):
    path: Literal["target", "fallback"]
    indexed: int
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    model: str
    model_revision: str | None = None


class CitationResolution(BaseModel):
    resolved: bool
    device_id: str | None = None
    norm_id: str | None = None
    artigo_id: str | None = None
    ambiguous: bool = False
    reason: str | None = None


class QueryPlan(BaseModel):
    fatos: QueryFacts
    consulta_juridica: str
    subperguntas: list[str] = Field(max_length=3)


class VerificationResult(BaseModel):
    ok: bool
    deterministic_ok: bool
    semantic_ok: bool | None = None
    issues: list[str] = Field(default_factory=list)
    action: Literal["accept", "regenerate", "abstain"]
    claims_supported: list[bool] = Field(default_factory=list)


class ModelFormatError(Exception):
    pass


class InvalidCitation(Exception):
    pass


class InsufficientEvidence(Exception):
    pass
