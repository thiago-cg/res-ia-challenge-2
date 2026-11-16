"""Adaptadores entre o grafo e a recuperação/geração existentes (T14).

O grafo (T06) não sabe chamar modelo nem banco: recebe três callables. Aqui estão as versões de
produção, que reaproveitam o pipeline já validado em vez de criar um segundo caminho de busca.

- decidir: classificacao deterministica do tipo de turno (sem custo de modelo);
- pesquisar: recuperacao real (servico extraido em T04) -> evidencias tipadas;
- sintetizar: geracao + verificacao existentes -> resposta candidata.

O estado é JSON-serializável; nenhum objeto de runtime entra nele (INV15).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from src.agents.contracts import RespostaConversa
from src.agents.state import AgentState

SAUDACOES = frozenset(
    {
        "oi",
        "ola",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite",
        "obrigada",
        "obrigado",
        "tchau",
        "e ai",
        "e aí",
    }
)


def _eh_social(pergunta: str) -> bool:
    texto = pergunta.strip().lower().strip(" .!?")
    return texto in SAUDACOES or len(texto) < 4


def decidir(estado: AgentState) -> dict[str, Any]:
    pergunta = estado.get("pergunta", "")
    if _eh_social(pergunta):
        return {"kind": "social", "proximo_passo": "sintetizar"}
    return {"kind": "juridica", "proximo_passo": "pesquisar"}


def construir_agentes(pipeline: Any) -> tuple[Any, Any, Any]:
    """Devolve (decidir, pesquisar, sintetizar) ligados a um pipeline concreto."""

    from src.services.retrieval import recuperar

    def _evidencias_web(pergunta: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Pesquisa web opcional (ADR-09). Falha vira lacuna, nunca derruba o turno."""

        settings = getattr(pipeline, "settings", None)
        if settings is None or not getattr(settings, "web_search_enabled", False):
            return [], []
        try:
            from src.services.web_search import PoliticaWeb
            from src.services.web_search import pesquisar as pesquisar_web

            dominios = tuple(
                d.strip()
                for d in str(getattr(settings, "web_search_allowlist", "")).split(",")
                if d.strip()
            )
            politica = PoliticaWeb(
                dominios_permitidos=dominios,
                max_resultados=settings.web_search_max_results,
            )
            pesquisa = pesquisar_web(pergunta, settings=settings, politica=politica)
        except Exception as exc:  # noqa: BLE001 - web fora do ar nao invalida o caminho local
            return [], [f"busca_web_indisponivel:{type(exc).__name__}"]
        evidencias = [item.model_dump(mode="json") for item in pesquisa.evidencias]
        lacunas = [] if pesquisa.suficiente else ["evidencia_web_insuficiente"]
        return evidencias, lacunas

    def pesquisar(estado: AgentState) -> dict[str, Any]:
        pergunta = estado.get("pergunta", "")
        web, lacunas_web = _evidencias_web(pergunta)
        recuperacao = recuperar(pergunta, None, pipeline.deps_recuperacao())
        if recuperacao.abstencao is not None or not recuperacao.devices:
            return {
                "resultado": {
                    "request_id": estado.get("turn_id", ""),
                    "status": "insuficiente",
                    "evidencias": web,
                    "lacunas": lacunas_web,
                }
            }
        evidencias = [
            {
                "kind": "base",
                "evidence_id": f"{d.device_id}@{d.norm_version_id}",
                "device_id": d.device_id,
                "norm_version_id": d.norm_version_id,
                "referencia_trecho": d.citacao,
            }
            for d in recuperacao.devices
        ]
        return {
            "resultado": {
                "request_id": estado.get("turn_id", ""),
                "status": "suficiente",
                # web nunca entra como dispositivo: entra como EvidenciaWeb (INV08)
                "evidencias": evidencias + web,
                "lacunas": lacunas_web,
            },
            "_devices": [d.model_dump(mode="json") for d in recuperacao.devices],
            "_facts": recuperacao.facts.model_dump(mode="json"),
            "_subperguntas": list(recuperacao.subperguntas),
        }

    def sintetizar(estado: AgentState) -> dict[str, Any]:
        from src.contracts import QueryFacts, RetrievedDevice

        devices = [RetrievedDevice(**item) for item in estado.get("_devices") or []]
        if not devices:
            resposta = RespostaConversa(kind="abstencao", texto=_texto_abstencao(), device_ids=[])
            return {"resposta": resposta.model_dump(), "kind": "abstencao"}

        facts = QueryFacts(**estado["_facts"]) if estado.get("_facts") else None
        resultado = pipeline._generate(  # noqa: SLF001 - núcleo reutilizado de propósito
            estado.get("pergunta", ""),
            facts,
            estado.get("_subperguntas") or [estado.get("pergunta", "")],
            devices,
        )
        answer = resultado.answer
        kind: Literal["juridica", "abstencao"] = "juridica" if answer.citacoes else "abstencao"
        resposta = RespostaConversa(
            kind=kind,
            texto=answer.resposta,
            device_ids=[c.device_id for c in answer.citacoes],
        )
        return {
            "resposta": resposta.model_dump(),
            "kind": kind,
            "_answer": answer.model_dump(mode="json"),
            "_emergencia": bool(resultado.emergencia),
            "_data_base": resultado.data_atualizacao_base,
        }

    return decidir, pesquisar, sintetizar


def _texto_abstencao() -> str:
    from src.agents.state import TEXTO_ABSTENCAO

    return TEXTO_ABSTENCAO


def projetar(estado: AgentState) -> dict[str, Any]:
    """Converte o estado final do grafo no payload público (ChatResponse)."""

    from src.api.schemas import ChatResponse
    from src.contracts import Answer
    from src.generate.fallback import abstain

    answer_dump = estado.get("_answer")
    if answer_dump:
        answer = Answer(**answer_dump)
    else:
        answer = abstain(
            estado.get("motivo_abstencao") or "sem_resposta",
            data_atualizacao=None,
        )
    data_base = estado.get("_data_base")
    resposta = ChatResponse.from_answer(
        answer,
        emergencia=bool(estado.get("_emergencia")),
        data_atualizacao_base=data_base if isinstance(data_base, str) else None,
    )
    return resposta.model_dump()


def novo_estado(*, conversation_id: uuid.UUID, run_id: uuid.UUID, pergunta: str) -> AgentState:
    from src.agents.state import estado_inicial

    return estado_inicial(
        conversation_id=str(conversation_id),
        turn_id=str(run_id),
        client_message_id=str(run_id),
        pergunta=pergunta,
    )
