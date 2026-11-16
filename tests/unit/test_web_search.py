"""T15 - pesquisa web (unidade, sem rede). Transporte HTTP injetado."""

from __future__ import annotations

import pytest

from src.config import Settings
from src.services.web_search import (
    CUSTO_SERPAPI_USD,
    BuscaWebDesabilitada,
    BuscaWebFalhou,
    BuscaWebIndisponivel,
    PoliticaWeb,
    pesquisar,
    url_aceitavel,
)


def _settings(**over) -> Settings:
    base = dict(
        web_search_enabled=True,
        web_search_provider="serpapi",
        serpapi_api_key="chave-serpapi",
        perplexity_api_key="chave-pplx",
        openrouter_api_key="chave-or",
        web_search_timeout=5.0,
    )
    base.update(over)
    return Settings(**base)


URL_PLANALTO = "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"


def _organicos() -> list[dict]:
    return [
        {
            "position": 1,
            "title": "Lei Maria da Penha",
            "link": URL_PLANALTO,
            "snippet": (
                "Art. 22. Constatada a pratica de violencia domestica, o juiz podera aplicar"
            ),
        }
    ]


def _transporte(payload, status=200, capturador=None):
    def _f(requisicao, timeout):
        if capturador is not None:
            capturador.append(requisicao)
        return status, payload

    return _f


def test_desligada_levanta() -> None:
    with pytest.raises(BuscaWebDesabilitada):
        pesquisar("pergunta", settings=_settings(web_search_enabled=False))


def test_sem_chave_levanta_indisponivel() -> None:
    with pytest.raises(BuscaWebIndisponivel, match="SERPAPI_API_KEY"):
        pesquisar("pergunta", settings=_settings(serpapi_api_key=""))


@pytest.mark.parametrize("pergunta", ["", "   "])
def test_pergunta_vazia_e_rejeitada(pergunta: str) -> None:
    with pytest.raises(ValueError):
        pesquisar(pergunta, settings=_settings(), transporte=_transporte({"organic_results": []}))


def test_pergunta_longa_e_recusada_em_vez_de_truncada() -> None:
    with pytest.raises(ValueError):
        pesquisar("x" * 800, settings=_settings(), transporte=_transporte({"organic_results": []}))


def test_requisicao_serpapi_segue_o_contrato() -> None:
    capturado: list = []
    pesquisar(
        "prazo para representar",
        settings=_settings(),
        transporte=_transporte({"organic_results": _organicos()}, capturador=capturado),
    )
    req = capturado[0]
    assert req.metodo == "GET"
    assert req.url == "https://serpapi.com/search"
    assert req.params["engine"] == "google_light"
    assert req.params["q"] == "prazo para representar"
    assert req.params["gl"] == "br" and req.params["hl"] == "pt"
    assert req.params["api_key"] == "chave-serpapi"
    assert req.corpo is None


def test_organic_results_viram_evidencia_web() -> None:
    pesquisa = pesquisar(
        "prazo para representar",
        settings=_settings(),
        transporte=_transporte({"organic_results": _organicos()}),
    )
    assert pesquisa.provedor == "serpapi"
    assert pesquisa.grounding_disponivel is True
    assert pesquisa.suficiente is True
    assert pesquisa.custo_usd == pytest.approx(CUSTO_SERPAPI_USD)
    ev = pesquisa.evidencias[0]
    assert ev.kind == "web"
    assert ev.url_validada == _organicos()[0]["link"]
    assert ev.publicador == "Lei Maria da Penha"
    assert ev.snapshot_hash.startswith("sha256:")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8080/x",
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com/lei",
        "javascript:alert(1)",
        "file:///C:/Windows/win.ini",
    ],
)
def test_url_perigosa_e_descartada(url: str) -> None:
    pesquisa = pesquisar(
        "pergunta",
        settings=_settings(),
        transporte=_transporte(
            {"organic_results": [{"title": "x", "link": url, "snippet": "trecho"}]}
        ),
    )
    assert pesquisa.evidencias == []
    assert pesquisa.descartadas
    assert pesquisa.suficiente is False


def test_allow_list_restringe_dominios() -> None:
    politica = PoliticaWeb(dominios_permitidos=("planalto.gov.br",))
    ok, _ = url_aceitavel("https://www.planalto.gov.br/x", politica)
    fora, motivo = url_aceitavel("https://exemplo.com/x", politica)
    assert ok is True
    assert fora is False and "fora da politica" in motivo


def test_erro_do_serpapi_levanta_falha() -> None:
    with pytest.raises(BuscaWebFalhou, match="serpapi"):
        pesquisar(
            "pergunta",
            settings=_settings(),
            transporte=_transporte({"error": "Invalid API key"}),
        )


def test_erro_http_levanta_falha_tipada() -> None:
    with pytest.raises(BuscaWebFalhou):
        pesquisar("pergunta", settings=_settings(), transporte=_transporte({}, status=500))


def test_custo_acima_do_teto_levanta() -> None:
    with pytest.raises(BuscaWebFalhou, match="teto"):
        pesquisar(
            "pergunta",
            settings=_settings(),
            politica=PoliticaWeb(teto_custo_usd=0.0001),
            transporte=_transporte({"organic_results": _organicos()}),
        )


def test_perplexity_continua_disponivel_como_alternativa() -> None:
    capturado: list = []
    pesquisa = pesquisar(
        "pergunta",
        settings=_settings(web_search_provider="perplexity"),
        transporte=_transporte({"search_results": [], "answers": {}}, capturador=capturado),
    )
    assert capturado[0].metodo == "POST"
    assert capturado[0].url == "https://api.perplexity.ai/v1/decisions"
    assert capturado[0].corpo["mode"] == "web_grounding"
    assert capturado[0].cabecalhos["Authorization"] == "Bearer chave-pplx"
    assert pesquisa.provedor == "perplexity"


def test_openrouter_nao_devolve_grounding_e_isso_e_reportado() -> None:
    capturado: list = []
    pesquisa = pesquisar(
        "pergunta",
        settings=_settings(web_search_provider="openrouter"),
        transporte=_transporte(
            {"answers": {"evidencia_suficiente": {"noul": 0.8}}}, capturador=capturado
        ),
    )
    assert capturado[0].url == "https://openrouter.ai/api/alpha/decisions"
    assert pesquisa.grounding_disponivel is False
    assert pesquisa.evidencias == []
    assert pesquisa.probabilidade == pytest.approx(0.8)
