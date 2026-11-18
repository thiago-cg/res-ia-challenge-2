"""Contratos entre o agente de conversa e o agente de pesquisa (T05).

Regras que estes modelos impõem (seção 7.5 do briefing de descoberta, materializada em
docs/12-multiagente-duravel-descobrimento-e-spec.md §21.3):

- "extra=forbid": campo desconhecido é erro, não é ignorado. O modelo não pode inventar
  "permitir_web", "fontes_permitidas" ou qualquer outro campo de política.
- A política é injetada pelo **código** ("PoliticaPesquisa"), nunca pelo modelo. Ela é "frozen",
  mas isso não substitui o limite de processo: "model_construct" ignora o congelamento.
- Evidência é união discriminada: uma evidência web não pode se apresentar como dispositivo da
  base (INV08). Não existe "source=web" em "RetrievedDevice".
- "hide_input_in_errors=True": mensagem de validação não ecoa o relato da pessoa. O worker trata
  essas exceções e o conteúdo não pode viajar grudado nelas.
- Divergência declarada em relação ao §8.1 (que é esboço): "fontes_permitidas" é tuple (hashável,
  coerente com frozen) e "deadline" é opcional (§8.1 previa obrigatório).

Estes modelos **não** ligam device_id a hidratação nem a citação canônica: essa verificação é de
"src.agents.policies" e do verificador existente. "Suficiente" é juízo do pesquisador, não
autorização de publicação — quem publica é o gate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Final = "pesquisa.v1"

#: Tipos de saída do agente de conversa. A política de publicação de cada um está em
#: "src.agents.policies"; aqui só a forma.
OutputKind = Literal["juridica", "esclarecimento", "social", "abstencao", "falha_tecnica"]

StatusPesquisa = Literal["suficiente", "parcial", "insuficiente", "precisa_esclarecimento", "erro"]

#: Item de lista. "max_length" na lista limita a quantidade, não o tamanho de cada item.
ItemCurto = Annotated[str, Field(min_length=1, max_length=500)]
DeviceIdStr = Annotated[str, Field(min_length=1, max_length=256)]


class _Fronteira(BaseModel):
    """Base comum: nada de campo extra entra pela fronteira e o erro não ecoa a entrada."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PedidoPesquisa(_Fronteira):
    """Pedido do agente de conversa para o agente de pesquisa."""

    schema_version: Literal["pesquisa.v1"] = SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    parent_request_id: str | None = Field(default=None, min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    pergunta_autossuficiente: str = Field(min_length=1, max_length=2000)
    contexto_minimo: str = Field(default="", max_length=4000)
    pontos_a_verificar: list[ItemCurto] = Field(default_factory=list, max_length=10)
    evidence_refs_anteriores: list[DeviceIdStr] = Field(default_factory=list, max_length=50)


class PoliticaPesquisa(_Fronteira):
    """Injetada pelo código. O modelo nunca escreve nela, e ela não muda depois de criada."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    permitir_web: bool = False
    fontes_permitidas: tuple[str, ...] = ()
    # P08: candidato não aprovado (§21.8)
    max_buscas: int = Field(default=3, ge=0, le=10)
    max_evidencias: int = Field(default=10, ge=0, le=20)
    # §21.7 exige deadline no run; aqui é opcional porque a política pode ser construída antes
    # de o run existir, e o worker impõe o prazo no claim.
    deadline: datetime | None = None
    orcamento_restante: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _web_exige_allowlist(self) -> PoliticaPesquisa:
        if self.permitir_web and not self.fontes_permitidas:
            raise ValueError("permitir_web exige fontes_permitidas não vazia")
        return self


class EvidenciaBase(_Fronteira):
    """Evidência que veio da base curada.

    O contrato garante a forma, não a procedência: ligar device_id a dispositivo realmente
    hidratado é trabalho de "src.agents.policies" (INV08, AC09/AC10).
    """

    kind: Literal["base"] = "base"
    evidence_id: str = Field(min_length=1, max_length=128)
    device_id: DeviceIdStr
    norm_version_id: int = Field(ge=1)
    referencia_trecho: str = Field(default="", max_length=500)
    pontos_sustentados: list[ItemCurto] = Field(default_factory=list, max_length=10)
    proveniencia: Literal["base"] = "base"


class EvidenciaWeb(_Fronteira):
    """Evidência externa. Nunca é ingestada automaticamente na base (ADR-09)."""

    kind: Literal["web"] = "web"
    evidence_id: str = Field(min_length=1, max_length=128)
    url_validada: str = Field(min_length=1, max_length=2048)
    publicador: str = Field(min_length=1, max_length=256)
    data_acesso: date
    data_publicacao: date | None = None
    trecho: str = Field(min_length=1, max_length=4000)
    snapshot_hash: str = Field(min_length=1, max_length=128)
    pontos_sustentados: list[ItemCurto] = Field(default_factory=list, max_length=10)

    @field_validator("url_validada")
    @classmethod
    def _apenas_http_com_host(cls, valor: str) -> str:
        partes = urlsplit(valor)
        if partes.scheme not in ("http", "https") or not partes.netloc:
            raise ValueError("url_validada precisa ser http(s) com host")
        return valor


Evidencia = Annotated[EvidenciaBase | EvidenciaWeb, Field(discriminator="kind")]


class ResultadoPesquisa(_Fronteira):
    """Resposta do pesquisador para o agente de conversa."""

    schema_version: Literal["pesquisa.v1"] = SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    status: StatusPesquisa
    evidencias: list[Evidencia] = Field(default_factory=list, max_length=20)
    lacunas: list[ItemCurto] = Field(default_factory=list, max_length=20)
    conflitos: list[ItemCurto] = Field(default_factory=list, max_length=20)
    esclarecimento_necessario: str | None = Field(default=None, max_length=500)
    erro_tipado: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _coerencia_do_status(self) -> ResultadoPesquisa:
        if self.status == "precisa_esclarecimento" and not self.esclarecimento_necessario:
            raise ValueError("status precisa_esclarecimento exige esclarecimento_necessario")
        if self.status != "precisa_esclarecimento" and self.esclarecimento_necessario:
            raise ValueError("esclarecimento_necessario só vale com status precisa_esclarecimento")
        if self.status == "erro" and not self.erro_tipado:
            raise ValueError("status erro exige erro_tipado")
        if self.status != "erro" and self.erro_tipado:
            raise ValueError("erro_tipado só vale com status erro")
        return self


class RespostaConversa(_Fronteira):
    """Saída do agente de conversa **antes** do gate de publicação.

    Não carrega "verificacao" (INV14): a projeção pública é montada em T14, e nada deve
    serializar este modelo direto para o navegador. As regras de coerência aqui são
    estruturais e baratas; a política completa fica em "src.agents.policies".
    """

    kind: OutputKind
    texto: str = Field(min_length=1, max_length=12000)
    device_ids: list[DeviceIdStr] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _coerencia_do_kind(self) -> RespostaConversa:
        if self.kind == "juridica" and not self.device_ids:
            raise ValueError("resposta jurídica exige ao menos um device_id")
        if self.kind != "juridica" and self.device_ids:
            raise ValueError(f"saída '{self.kind}' não pode citar dispositivo")
        return self
