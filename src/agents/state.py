"""Estado do grafo (T06).

Só dado serializável. Nada de cliente HTTP, conexão, lock ou objeto de runtime — o estado vai para
checkpoint e para a projeção pública, e o que não for JSON não tem lugar aqui (INV15).
"""

from __future__ import annotations

from typing import Any, TypedDict


class Orcamento(TypedDict, total=False):
    chamadas_pesquisa: int
    tentativas_publicacao: int
    chamadas_llm: int
    tokens: int


class AgentState(TypedDict, total=False):
    # identidade do turno
    conversation_id: str
    turn_id: str
    client_message_id: str
    # entrada
    pergunta: str
    facts: dict[str, Any] | None
    # decisão do agente de conversa
    kind: str
    proximo_passo: str
    pedido: dict[str, Any] | None
    # pesquisa
    resultado: dict[str, Any] | None
    # síntese
    resposta: dict[str, Any] | None
    texto: str
    # validação e publicação
    publicavel: bool
    motivo_abstencao: str | None
    # controle
    orcamento: Orcamento
    # material interno do processador (serializável; nunca vai ao navegador)
    _devices: list[dict[str, Any]]
    _facts: dict[str, Any]
    _subperguntas: list[str]
    _answer: dict[str, Any]
    _emergencia: bool
    _data_base: str | None


TEXTO_ABSTENCAO = (
    "Não encontrei base suficiente para responder com segurança. "
    "Se você está em perigo, ligue 190. A Central de Atendimento à Mulher atende no 180."
)


def estado_inicial(
    *,
    conversation_id: str,
    turn_id: str,
    client_message_id: str,
    pergunta: str,
    facts: dict[str, Any] | None = None,
    chamadas_pesquisa: int = 2,
) -> AgentState:
    """Estado mínimo e serializável de um turno."""

    return AgentState(
        conversation_id=conversation_id,
        turn_id=turn_id,
        client_message_id=client_message_id,
        pergunta=pergunta,
        facts=facts,
        orcamento=Orcamento(chamadas_pesquisa=chamadas_pesquisa, tentativas_publicacao=0),
        publicavel=False,
    )
