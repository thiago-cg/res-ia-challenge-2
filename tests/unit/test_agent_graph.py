"""T06 — grafo com agentes fake: rotas, loops e limites.

Nenhum LLM, nenhum banco, nenhuma rede. O grafo é orquestração determinística; os dois nós que
chamam modelo são injetados. Este arquivo existe antes de src/agents/graph.py (RED).
"""

from __future__ import annotations


def _contratos():
    from src.agents import contracts as c

    return c


def _evidencia_base(device_id: str = "lmp/art22", versao: int = 7) -> dict:
    return {
        "kind": "base",
        "evidence_id": f"e-{device_id}",
        "device_id": device_id,
        "norm_version_id": versao,
    }


def _resultado(status: str = "suficiente", evidencias: list[dict] | None = None) -> dict:
    return {
        "request_id": "r-1",
        "status": status,
        "evidencias": evidencias if evidencias is not None else [_evidencia_base()],
    }


def _grafo(*, decidir, pesquisar=None, sintetizar=None, max_tentativas: int = 2):
    from src.agents.graph import build_graph

    return build_graph(
        decidir=decidir,
        pesquisar=pesquisar or (lambda estado: {"resultado": _resultado()}),
        sintetizar=sintetizar
        or (
            lambda estado: {
                "resposta": {"kind": estado["kind"], "texto": "ok", "device_ids": ["lmp/art22"]}
            }
        ),
        max_tentativas=max_tentativas,
    )


def _inicial(**over):
    base = {
        "conversation_id": "c-1",
        "turn_id": "t-1",
        "client_message_id": "m-1",
        "pergunta": "Qual o prazo?",
        "orcamento": {"chamadas_pesquisa": 2, "tentativas_publicacao": 0},
    }
    base.update(over)
    return base


def test_social_nao_pesquisa() -> None:
    chamadas: list[str] = []

    def decidir(estado):
        return {"kind": "social", "proximo_passo": "sintetizar"}

    def sintetizar(estado):
        chamadas.append("sintetizar")
        return {"resposta": {"kind": "social", "texto": "olá", "device_ids": []}}

    grafo = _grafo(decidir=decidir, sintetizar=sintetizar)
    final = grafo.invoke(_inicial())

    assert chamadas == ["sintetizar"]
    assert final["kind"] == "social"
    assert final["publicavel"] is True


def test_juridica_pesquisa_antes_de_sintetizar() -> None:
    ordem: list[str] = []

    def decidir(estado):
        return {
            "kind": "juridica",
            "proximo_passo": "pesquisar",
            "pedido": {"request_id": "r-1", "turn_id": "t-1", "pergunta_autossuficiente": "prazo"},
        }

    def pesquisar(estado):
        ordem.append("pesquisar")
        return {"resultado": _resultado()}

    def sintetizar(estado):
        ordem.append("sintetizar")
        return {"resposta": {"kind": "juridica", "texto": "a lei diz", "device_ids": ["lmp/art22"]}}

    grafo = _grafo(decidir=decidir, pesquisar=pesquisar, sintetizar=sintetizar)
    final = grafo.invoke(_inicial())

    assert ordem == ["pesquisar", "sintetizar"]
    assert final["publicavel"] is True


def test_evidencia_insuficiente_vira_abstencao() -> None:
    def decidir(estado):
        return {
            "kind": "juridica",
            "proximo_passo": "pesquisar",
            "pedido": {"request_id": "r-1", "turn_id": "t-1", "pergunta_autossuficiente": "x"},
        }

    def sintetizar(estado):  # pragma: no cover - não deve ser chamado
        raise AssertionError("não deveria sintetizar sem evidência")

    grafo = _grafo(
        decidir=decidir,
        pesquisar=lambda e: {"resultado": _resultado("insuficiente", [])},
        sintetizar=sintetizar,
    )
    final = grafo.invoke(_inicial())

    assert final["kind"] == "abstencao"
    assert final["publicavel"] is True
    assert final.get("motivo_abstencao")


def test_esclarecimento_encerra_sem_pesquisa() -> None:
    def decidir(estado):
        return {"kind": "esclarecimento", "proximo_passo": "sintetizar"}

    def sintetizar(estado):
        return {
            "resposta": {
                "kind": "esclarecimento",
                "texto": "Você quer falar do fato de quando?",
                "device_ids": [],
            }
        }

    grafo = _grafo(decidir=decidir, sintetizar=sintetizar)
    final = grafo.invoke(_inicial())

    assert final["kind"] == "esclarecimento"
    assert final["publicavel"] is True


def test_pesquisador_que_pede_esclarecimento_nao_publica_juridico() -> None:
    def decidir(estado):
        return {
            "kind": "juridica",
            "proximo_passo": "pesquisar",
            "pedido": {"request_id": "r-1", "turn_id": "t-1", "pergunta_autossuficiente": "x"},
        }

    def sintetizar(estado):  # pragma: no cover
        raise AssertionError("não deveria sintetizar resposta jurídica")

    resultado = _resultado("precisa_esclarecimento", [])
    resultado["esclarecimento_necessario"] = "Quando aconteceu?"
    grafo = _grafo(
        decidir=decidir, pesquisar=lambda e: {"resultado": resultado}, sintetizar=sintetizar
    )
    final = grafo.invoke(_inicial())

    assert final["kind"] == "esclarecimento"
    assert "Quando aconteceu?" in final["texto"]


def test_orcamento_de_pesquisa_esgotado_vira_abstencao() -> None:
    def decidir(estado):
        return {
            "kind": "juridica",
            "proximo_passo": "pesquisar",
            "pedido": {"request_id": "r-1", "turn_id": "t-1", "pergunta_autossuficiente": "x"},
        }

    def pesquisar(estado):  # pragma: no cover
        raise AssertionError("não deveria pesquisar sem orçamento")

    grafo = _grafo(decidir=decidir, pesquisar=pesquisar, max_tentativas=1)
    final = grafo.invoke(_inicial(orcamento={"chamadas_pesquisa": 0, "tentativas_publicacao": 0}))

    assert final["kind"] == "abstencao"
    assert final["motivo_abstencao"] == "orcamento_esgotado"


def test_politica_recusa_juridica_sem_evidencia_e_abstem() -> None:
    def decidir(estado):
        return {
            "kind": "juridica",
            "proximo_passo": "pesquisar",
            "pedido": {"request_id": "r-1", "turn_id": "t-1", "pergunta_autossuficiente": "x"},
        }

    def sintetizar(estado):
        return {"resposta": {"kind": "juridica", "texto": "inventei", "device_ids": ["lmp/art999"]}}

    grafo = _grafo(
        decidir=decidir,
        pesquisar=lambda e: {"resultado": _resultado()},
        sintetizar=sintetizar,
        max_tentativas=1,
    )
    final = grafo.invoke(_inicial())

    assert final["kind"] == "abstencao"
    assert final["publicavel"] is True


def test_regeneracao_e_limitada_pelo_orcamento() -> None:
    tentativas: list[int] = []

    def decidir(estado):
        return {
            "kind": "juridica",
            "proximo_passo": "pesquisar",
            "pedido": {"request_id": "r-1", "turn_id": "t-1", "pergunta_autossuficiente": "x"},
        }

    def sintetizar(estado):
        tentativas.append(estado["orcamento"]["tentativas_publicacao"])
        return {"resposta": {"kind": "juridica", "texto": "inventei", "device_ids": ["lmp/art999"]}}

    grafo = _grafo(
        decidir=decidir,
        pesquisar=lambda e: {"resultado": _resultado()},
        sintetizar=sintetizar,
        max_tentativas=2,
    )
    final = grafo.invoke(_inicial())

    assert len(tentativas) == 2, "deve tentar exatamente max_tentativas vezes"
    assert final["kind"] == "abstencao"


def test_estado_final_e_serializavel_e_sem_objetos_de_runtime() -> None:
    import json

    def decidir(estado):
        return {"kind": "social", "proximo_passo": "sintetizar"}

    def sintetizar(estado):
        return {"resposta": {"kind": "social", "texto": "olá", "device_ids": []}}

    final = _grafo(decidir=decidir, sintetizar=sintetizar).invoke(_inicial())
    json.dumps(final)  # não pode levantar


def test_contratos_do_grafo_sao_os_de_t05() -> None:
    c = _contratos()
    for nome in ("PedidoPesquisa", "ResultadoPesquisa", "RespostaConversa", "PoliticaPesquisa"):
        assert hasattr(c, nome)
