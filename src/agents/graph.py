"""Grafo dos dois agentes (T06).

Dois nós chamam modelo — `decidir` (conversa) e `sintetizar` (conversa) e `pesquisar` (pesquisa) —
e são **injetados** por quem monta o grafo. Tudo o mais aqui é determinístico: orçamento,
roteamento, detecção de evidência insuficiente e o gate de publicação.

Consequência prática: o grafo é testável sem LLM, sem rede e sem banco, e nenhuma decisão de
política depende do humor do modelo.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.policies import validar_resposta
from src.agents.state import TEXTO_ABSTENCAO, AgentState, Orcamento

Decidir = Callable[[AgentState], dict[str, Any]]
Pesquisar = Callable[[AgentState], dict[str, Any]]
Sintetizar = Callable[[AgentState], dict[str, Any]]


def _orcamento(estado: AgentState) -> Orcamento:
    bruto = estado.get("orcamento") or {}
    return Orcamento(
        chamadas_pesquisa=int(bruto.get("chamadas_pesquisa", 0)),
        tentativas_publicacao=int(bruto.get("tentativas_publicacao", 0)),
        chamadas_llm=int(bruto.get("chamadas_llm", 0)),
        tokens=int(bruto.get("tokens", 0)),
    )


def _motivo_da_abstencao(estado: AgentState) -> str:
    motivo = estado.get("abstencao") or estado.get("motivo_abstencao")
    if motivo:
        return str(motivo)
    resultado = estado.get("resultado") or {}
    status = resultado.get("status")
    if status == "insuficiente":
        return "evidencia_insuficiente"
    if status == "erro":
        return str(resultado.get("erro_tipado") or "erro_pesquisa")
    return "evidencia_insuficiente"


def build_graph(
    *,
    decidir: Decidir,
    pesquisar: Pesquisar,
    sintetizar: Sintetizar,
    max_tentativas: int = 2,
    checkpointer: Any = None,
):
    """Monta o grafo. `checkpointer=None` mantém tudo em memória (usado nos testes)."""

    def no_decidir(estado: AgentState) -> dict[str, Any]:
        return dict(decidir(estado) or {})

    def no_pesquisar(estado: AgentState) -> dict[str, Any]:
        orcamento = _orcamento(estado)
        restante = int(orcamento.get("chamadas_pesquisa", 0))
        if restante <= 0:
            return {"motivo_abstencao": "orcamento_esgotado"}
        orcamento["chamadas_pesquisa"] = restante - 1
        novo = dict(pesquisar(estado) or {})
        novo["orcamento"] = orcamento
        return novo

    def no_sintetizar(estado: AgentState) -> dict[str, Any]:
        return dict(sintetizar(estado) or {})

    def no_esclarecer(estado: AgentState) -> dict[str, Any]:
        resultado = estado.get("resultado") or {}
        pergunta = resultado.get("esclarecimento_necessario") or (
            "Você pode me dar um detalhe a mais sobre o que aconteceu?"
        )
        return {
            "kind": "esclarecimento",
            "texto": str(pergunta),
            "publicavel": True,
            "motivo_abstencao": None,
        }

    def no_abster(estado: AgentState) -> dict[str, Any]:
        return {
            "kind": "abstencao",
            "texto": TEXTO_ABSTENCAO,
            "publicavel": True,
            "motivo_abstencao": _motivo_da_abstencao(estado),
        }

    def no_validar(estado: AgentState) -> dict[str, Any]:
        resultado = estado.get("resultado") or {}
        evidencias = resultado.get("evidencias") or []
        problemas = validar_resposta(estado.get("resposta"), evidencias)

        if not problemas:
            resposta = estado.get("resposta") or {}
            return {
                "publicavel": True,
                "kind": resposta.get("kind", estado.get("kind", "falha_tecnica")),
                "texto": resposta.get("texto", ""),
                "motivo_abstencao": None,
            }

        orcamento = _orcamento(estado)
        tentativas = int(orcamento.get("tentativas_publicacao", 0)) + 1
        orcamento["tentativas_publicacao"] = tentativas
        if tentativas >= max_tentativas:
            return {
                "orcamento": orcamento,
                "publicavel": True,
                "kind": "abstencao",
                "texto": TEXTO_ABSTENCAO,
                "motivo_abstencao": "publicacao_recusada",
            }
        return {"orcamento": orcamento, "publicavel": False}

    def rota_decidir(estado: AgentState) -> str:
        return "pesquisar" if estado.get("proximo_passo") == "pesquisar" else "sintetizar"

    def rota_pesquisa(estado: AgentState) -> str:
        if estado.get("motivo_abstencao"):
            return "abster"
        resultado = estado.get("resultado") or {}
        status = resultado.get("status")
        if status == "precisa_esclarecimento":
            return "esclarecer"
        if status in ("insuficiente", "erro"):
            return "abster"
        if not resultado.get("evidencias"):
            return "abster"
        return "sintetizar"

    def rota_validar(estado: AgentState) -> str:
        return END if estado.get("publicavel") else "sintetizar"

    # O tipstub do LangGraph não aceita a assinatura de nó que usamos (dict parcial);
    # o builder fica opaco para o mypy e o estado continua tipado.
    construtor: Any = StateGraph(AgentState)
    construtor.add_node("decidir", no_decidir)
    construtor.add_node("pesquisar", no_pesquisar)
    construtor.add_node("sintetizar", no_sintetizar)
    construtor.add_node("validar", no_validar)
    construtor.add_node("esclarecer", no_esclarecer)
    construtor.add_node("abster", no_abster)

    construtor.add_edge(START, "decidir")
    construtor.add_conditional_edges(
        "decidir", rota_decidir, {"pesquisar": "pesquisar", "sintetizar": "sintetizar"}
    )
    construtor.add_conditional_edges(
        "pesquisar",
        rota_pesquisa,
        {"abster": "abster", "esclarecer": "esclarecer", "sintetizar": "sintetizar"},
    )
    construtor.add_edge("sintetizar", "validar")
    construtor.add_conditional_edges(
        "validar", rota_validar, {END: END, "sintetizar": "sintetizar"}
    )
    construtor.add_edge("esclarecer", END)
    construtor.add_edge("abster", END)

    return construtor.compile(checkpointer=checkpointer)
