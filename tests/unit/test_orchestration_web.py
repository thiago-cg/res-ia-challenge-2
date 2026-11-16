"""A evidencia web entra no resultado da pesquisa sem se disfarcar de base (INV08)."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.contracts import EvidenciaWeb
from src.services import orchestration


class _PipelineFake:
    def __init__(self, web_ligada: bool) -> None:
        self.settings = SimpleNamespace(
            web_search_enabled=web_ligada,
            web_search_allowlist="",
            web_search_max_results=5,
        )

    def deps_recuperacao(self):
        return None


def _recuperacao():
    from src.contracts import QueryFacts, RetrievedDevice

    device = RetrievedDevice(
        device_id="lmp/art22",
        norm_version_id=7,
        score=0.5,
        source="bm25",
        texto_literal="Art. 22 ...",
        citacao="Lei 11.340/2006, art. 22",
    )
    return SimpleNamespace(
        abstencao=None,
        devices=[device],
        facts=QueryFacts(
            relacao="desconhecido",
            tipo_violencia=[],
            urgencia="desconhecida",
            data_fato=None,
            uf=None,
        ),
        subperguntas=("p",),
    )


def test_web_entra_como_evidencia_web_e_nao_como_dispositivo(monkeypatch) -> None:
    monkeypatch.setattr("src.services.retrieval.recuperar", lambda *a, **k: _recuperacao())

    evidencia = EvidenciaWeb(
        evidence_id="e-web",
        url_validada="https://www.planalto.gov.br/x",
        publicador="Planalto",
        data_acesso="2026-11-16",
        trecho="trecho",
        snapshot_hash="sha256:abc",
    )
    monkeypatch.setattr(
        "src.services.web_search.pesquisar",
        lambda *a, **k: SimpleNamespace(evidencias=[evidencia], suficiente=True),
    )

    _, pesquisar, _ = orchestration.construir_agentes(_PipelineFake(web_ligada=True))
    saida = pesquisar({"pergunta": "Qual o prazo?", "turn_id": "t1"})
    evidencias = saida["resultado"]["evidencias"]
    assert [e["kind"] for e in evidencias] == ["base", "web"]
    assert saida["resultado"]["lacunas"] == []


def test_web_desligada_nao_chama_a_busca(monkeypatch) -> None:
    monkeypatch.setattr("src.services.retrieval.recuperar", lambda *a, **k: _recuperacao())

    def explode(*a, **k):
        raise AssertionError("nao deveria pesquisar na web")

    monkeypatch.setattr("src.services.web_search.pesquisar", explode)
    _, pesquisar, _ = orchestration.construir_agentes(_PipelineFake(web_ligada=False))
    saida = pesquisar({"pergunta": "Qual o prazo?", "turn_id": "t1"})
    assert [e["kind"] for e in saida["resultado"]["evidencias"]] == ["base"]


def test_falha_da_busca_web_nao_derruba_o_turno(monkeypatch) -> None:
    monkeypatch.setattr("src.services.retrieval.recuperar", lambda *a, **k: _recuperacao())

    def falha(*a, **k):
        raise RuntimeError("api fora")

    monkeypatch.setattr("src.services.web_search.pesquisar", falha)
    _, pesquisar, _ = orchestration.construir_agentes(_PipelineFake(web_ligada=True))
    saida = pesquisar({"pergunta": "Qual o prazo?", "turn_id": "t1"})
    assert saida["resultado"]["lacunas"] == ["busca_web_indisponivel:RuntimeError"]
    assert [e["kind"] for e in saida["resultado"]["evidencias"]] == ["base"]
