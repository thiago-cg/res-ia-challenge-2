"""Pesquisa web para o agente de pesquisa (T15, ADR-09).

Provedor padrao: SerpApi engine google_light (GET https://serpapi.com/search?engine=google_light).
Contrato conferido em 2026-11-16: engine, q, gl, hl; resultados em organic_results
(position, title, link, snippet); erro vem em "error". Custo US$ 0,015 por chamada bem-sucedida,
p50 11 s / p95 44 s, por isso o timeout padrao e 60 s.

Alternativas mantidas: perplexity (Decisions API nativa, unica com mode=web_grounding e
search_results) e openrouter (mesmo modelo decisor, que responde 200 sem evidencia - medido).

Seguranca aplicada aqui, nao no provedor: so sai pergunta minimizada (recusa em vez de truncar);
toda URL e validada (http/https, host publico, allow-list) e loopback/metadata/esquemas perigosos
sao descartados; o que volta vira EvidenciaWeb, nunca RetrievedDevice (INV08); nada e ingerido.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from src.agents.contracts import EvidenciaWeb
from src.config import Settings

CUSTO_SERPAPI_USD = 0.015
CUSTO_BUSCA_PERPLEXITY_USD = 0.001

_HOSTS_PROIBIDOS = ("localhost", "127.", "0.0.0.0", "169.254.", "::1", "metadata.google.internal")


class ErroBuscaWeb(RuntimeError):
    """Base dos erros de pesquisa web."""


class BuscaWebDesabilitada(ErroBuscaWeb):
    """WEB_SEARCH_ENABLED=false."""


class BuscaWebIndisponivel(ErroBuscaWeb):
    """Falta credencial ou configuracao."""


class BuscaWebFalhou(ErroBuscaWeb):
    """Provedor respondeu com erro ou fora do contrato."""


@dataclass(frozen=True)
class PoliticaWeb:
    dominios_permitidos: tuple[str, ...] = ()
    max_resultados: int = 5
    max_staleness: int = 86_400
    limiar_noul: float = 0.5
    teto_custo_usd: float = 0.05


@dataclass(frozen=True)
class Requisicao:
    """Pedido HTTP montado: GET usa params, POST usa corpo JSON."""

    metodo: str
    url: str
    cabecalhos: dict[str, str] = field(default_factory=dict)
    corpo: dict[str, Any] | None = None
    params: dict[str, str] | None = None


Transporte = Callable[[Requisicao, float], tuple[int, dict[str, Any]]]


@dataclass(frozen=True)
class PesquisaWeb:
    evidencias: list[EvidenciaWeb] = field(default_factory=list)
    probabilidade: float | None = None
    suficiente: bool = False
    descartadas: list[str] = field(default_factory=list)
    custo_usd: float = 0.0
    modelo: str = ""
    provedor: str = ""
    grounding_disponivel: bool = False

    @property
    def vazia(self) -> bool:
        return not self.evidencias


def _host_publico(host: str, politica: PoliticaWeb) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    for proibido in _HOSTS_PROIBIDOS:
        if host == proibido or host.startswith(proibido):
            return False
    if politica.dominios_permitidos:
        return any(
            host == dominio or host.endswith("." + dominio)
            for dominio in politica.dominios_permitidos
        )
    return True


def url_aceitavel(url: str, politica: PoliticaWeb) -> tuple[bool, str]:
    partes = urlsplit(url or "")
    if partes.scheme not in ("http", "https"):
        return False, "esquema nao permitido"
    if not partes.hostname:
        return False, "sem host"
    if not _host_publico(partes.hostname, politica):
        return False, "host fora da politica"
    return True, ""


def _texto_curto(valor: Any, limite: int) -> str:
    return " ".join(str(valor or "").split())[:limite]


def _resultados(payload: dict[str, Any], provedor: str) -> list[dict[str, Any]]:
    if provedor == "serpapi":
        return list(payload.get("organic_results") or [])
    return list(payload.get("search_results") or [])


def _url_do_item(item: dict[str, Any], provedor: str) -> str:
    if provedor == "serpapi":
        return str(item.get("link") or "")
    return str(item.get("url") or "")


def _traduzir(
    resultados: list[dict[str, Any]], politica: PoliticaWeb, provedor: str
) -> tuple[list[EvidenciaWeb], list[str]]:
    evidencias: list[EvidenciaWeb] = []
    descartadas: list[str] = []
    for item in resultados[: politica.max_resultados]:
        url = _url_do_item(item, provedor)
        ok, motivo = url_aceitavel(url, politica)
        if not ok:
            descartadas.append(f"{url or '(sem url)'}: {motivo}")
            continue
        snippet = _texto_curto(item.get("snippet"), 2000)
        if not snippet:
            descartadas.append(f"{url}: sem trecho")
            continue
        host = urlsplit(url).hostname or ""
        evidencias.append(
            EvidenciaWeb(
                evidence_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
                url_validada=url,
                publicador=_texto_curto(item.get("title") or host, 256) or host,
                data_acesso=date.today(),
                trecho=snippet,
                snapshot_hash="sha256:" + hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
            )
        )
    return evidencias, descartadas


def montar_requisicao(pergunta: str, *, settings: Settings, politica: PoliticaWeb) -> Requisicao:
    if settings.web_search_provider == "serpapi":
        return Requisicao(
            metodo="GET",
            url=settings.serpapi_base_url.rstrip("/") + "/search",
            params={
                "engine": settings.serpapi_engine,
                "q": pergunta,
                "gl": settings.serpapi_gl,
                "hl": settings.serpapi_hl,
            },
        )

    corpo: dict[str, Any] = {
        "state": pergunta,
        "questions": {
            "evidencia_suficiente": {
                "type": "noul",
                "instructions": (
                    "As fontes encontradas sustentam uma resposta oficial e verificavel "
                    "para a pergunta?"
                ),
            }
        },
    }
    if settings.web_search_provider == "perplexity":
        corpo["model"] = settings.web_search_model
        corpo["mode"] = "web_grounding"
        corpo["max_staleness"] = politica.max_staleness
        return Requisicao(
            metodo="POST",
            url=settings.perplexity_base_url.rstrip("/") + "/v1/decisions",
            cabecalhos={"Content-Type": "application/json"},
            corpo=corpo,
        )

    base = settings.openrouter_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    corpo["model"] = f"perplexity/{settings.web_search_model}"
    corpo["mode"] = "web_grounding"
    return Requisicao(
        metodo="POST",
        url=base + "/alpha/decisions",
        cabecalhos={"Content-Type": "application/json"},
        corpo=corpo,
    )


def _credencial(settings: Settings) -> tuple[str, str]:
    if settings.web_search_provider == "serpapi":
        return settings.serpapi_api_key, "SERPAPI_API_KEY"
    if settings.web_search_provider == "perplexity":
        return settings.perplexity_api_key, "PERPLEXITY_API_KEY"
    return settings.openrouter_api_key, "OPENROUTER_API_KEY"


def pesquisar(
    pergunta: str,
    *,
    settings: Settings,
    politica: PoliticaWeb | None = None,
    transporte: Transporte | None = None,
) -> PesquisaWeb:
    if not settings.web_search_enabled:
        raise BuscaWebDesabilitada("WEB_SEARCH_ENABLED=false: pesquisa web nao autorizada (ADR-09)")

    chave, nome_variavel = _credencial(settings)
    if not chave:
        raise BuscaWebIndisponivel(
            f"sem credencial para {settings.web_search_provider}: defina {nome_variavel}"
        )

    pergunta = " ".join((pergunta or "").split())
    if not pergunta:
        raise ValueError("pergunta vazia")
    if len(pergunta) > settings.web_search_max_caracteres_pergunta:
        raise ValueError(
            "pergunta acima do limite de minimizacao; envie a versao autossuficiente e curta"
        )

    regra = politica or PoliticaWeb(
        max_resultados=settings.web_search_max_results,
        max_staleness=settings.web_search_max_staleness,
    )
    requisicao = montar_requisicao(pergunta, settings=settings, politica=regra)
    if requisicao.params is not None:
        requisicao.params["api_key"] = chave
    else:
        requisicao.cabecalhos["Authorization"] = f"Bearer {chave}"

    transporte = transporte or _transporte_httpx
    status, payload = transporte(requisicao, settings.web_search_timeout)
    if status >= 400:
        raise BuscaWebFalhou(f"provedor respondeu {status}")

    provedor = settings.web_search_provider
    if provedor == "serpapi" and payload.get("error"):
        raise BuscaWebFalhou(f"serpapi: {str(payload['error'])[:200]}")

    resultados = _resultados(payload, provedor)
    evidencias, descartadas = _traduzir(resultados, regra, provedor)

    resposta = (payload.get("answers") or {}).get("evidencia_suficiente") or {}
    noul = resposta.get("noul")
    probabilidade = float(noul) if isinstance(noul, (int, float)) else None

    uso = payload.get("usage") or {}
    if provedor == "serpapi":
        custo = CUSTO_SERPAPI_USD if resultados else 0.0
    elif provedor == "perplexity":
        custo = float(uso.get("cost") or 0.0) + (CUSTO_BUSCA_PERPLEXITY_USD if resultados else 0.0)
    else:
        custo = float(uso.get("cost") or 0.0)
    if custo > regra.teto_custo_usd:
        raise BuscaWebFalhou("custo estimado acima do teto da politica")

    suficiente = (
        bool(evidencias)
        if probabilidade is None
        else bool(evidencias and probabilidade >= regra.limiar_noul)
    )

    return PesquisaWeb(
        evidencias=evidencias,
        probabilidade=probabilidade,
        suficiente=suficiente,
        descartadas=descartadas,
        custo_usd=round(custo, 6),
        modelo=str(payload.get("model") or settings.web_search_model),
        provedor=provedor,
        grounding_disponivel=bool(resultados),
    )


def _transporte_httpx(requisicao: Requisicao, timeout: float) -> tuple[int, dict[str, Any]]:
    import httpx

    with httpx.Client(timeout=timeout) as cliente:
        if requisicao.metodo == "GET":
            resposta = cliente.get(
                requisicao.url, params=requisicao.params, headers=requisicao.cabecalhos
            )
        else:
            resposta = cliente.post(
                requisicao.url, json=requisicao.corpo, headers=requisicao.cabecalhos
            )
        try:
            dados = resposta.json()
        except Exception as exc:  # noqa: BLE001 - corpo nao-JSON vira falha tipada
            raise BuscaWebFalhou(f"resposta nao-JSON (HTTP {resposta.status_code})") from exc
        return resposta.status_code, dados
