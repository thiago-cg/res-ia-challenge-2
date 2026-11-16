"""Recuperação como serviço (T04).

Extraído de `LegalRAGPipeline.answer` sem mudar comportamento: a ordem das etapas, os motivos de
abstenção e o par (facts, subperguntas) que segue para a geração são idênticos aos de
`src/api/main.py:390-473` antes da extração. A suíte existente (`tests/unit/test_api.py`, 39
testes) é a caracterização que prova a equivalência.

O que este serviço **não** faz: roteamento de risco e geração de resposta. Risco é decisão de
segurança e continua fora, no chamador, antes de qualquer I/O (INV09).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.config import Settings
from src.contracts import (
    CitationResolution,
    QueryFacts,
    QueryPlan,
    RetrievedDevice,
)
from src.index.embed import Encoder
from src.retrieve.citations import CitationCatalog, resolve_explicit_citation
from src.retrieve.expand import dedupe_by_artigo, expand_to_article
from src.retrieve.hybrid import DenseSearcher, FtsSearcher, QdrantSearcher, hybrid_search
from src.retrieve.hydrate import hydrate
from src.retrieve.query import default_facts, extract_data_fato, understand_query
from src.retrieve.rerank import MultiVectorEncoder, Rescore, rerank


def as_rerank_encoder(
    encoder: Encoder | MultiVectorEncoder | None,
) -> MultiVectorEncoder | None:
    """Só encoders com `encode_document` servem para rerank por MaxSim."""

    if encoder is None:
        return None
    if callable(getattr(encoder, "encode_document", None)):
        return encoder  # type: ignore[return-value]
    return None


@dataclass(frozen=True)
class DepsRecuperacao:
    """Dependências da recuperação, injetadas pelo chamador (nunca montadas aqui)."""

    repo: Any
    settings: Settings
    dense: DenseSearcher | None = None
    fts: FtsSearcher | None = None
    qdrant: QdrantSearcher | None = None
    encoder: Any = None
    rescore: Rescore | None = None
    catalog: CitationCatalog | None = None
    rewrite: Callable[[str], str] | None = None
    rerank_encoder: MultiVectorEncoder | None = None


@dataclass(frozen=True)
class Recuperacao:
    """Resultado da recuperação: ou dispositivos para gerar, ou motivo de abstenção."""

    facts: QueryFacts
    subperguntas: tuple[str, ...]
    devices: tuple[RetrievedDevice, ...] = ()
    retrieved_ids: tuple[str, ...] = ()
    abstencao: str | None = None


def recuperar(
    message: str,
    facts: QueryFacts | None,
    deps: DepsRecuperacao,
) -> Recuperacao:
    """Executa exatamente o caminho de recuperação do pipeline original."""

    facts = with_extracted_data_fato(message, facts)

    try:
        resolution = resolve_explicit_citation(
            message,
            catalog=deps.catalog,
            data_fato=facts.data_fato if facts else None,
        )
    except Exception:
        return Recuperacao(facts or default_facts(), (message,), abstencao="erro_recuperacao")

    if resolution.resolved:
        base = facts or default_facts()
        try:
            explicit = explicit_devices(resolution, base, deps)
        except Exception:
            return Recuperacao(base, (message,), abstencao="erro_recuperacao")
        if not explicit:
            return Recuperacao(base, (message,), abstencao="citacao_explicita_sem_versao_vigente")
        return Recuperacao(
            base,
            (message,),
            devices=tuple(explicit),
            retrieved_ids=tuple(item.device_id for item in explicit),
        )

    if is_explicit_miss(resolution):
        return Recuperacao(
            facts or default_facts(), (message,), abstencao="citacao_explicita_nao_encontrada"
        )

    plan = understand_query(
        message,
        facts,
        max_subquestions=deps.settings.max_subquestions,
        expand=deps.settings.query_expansion,
        llm_call=(
            deps.rewrite
            if deps.settings.query_rewrite == "llm" and deps.rewrite is not None
            else None
        ),
    )

    try:
        candidates = hybrid_search(
            plan,
            dense=deps.dense,
            fts=deps.fts,
            qdrant=deps.qdrant,
            path=deps.settings.retrieval_path,
            data_fato=plan.fatos.data_fato,
            lexical_weight=deps.settings.hybrid_lexical_weight,
        )
    except Exception:
        return _abstain_rec(plan, "falha_na_recuperacao")

    if not candidates:
        return _abstain_rec(plan, "nenhum_dispositivo_recuperado")

    # Reranker lê o texto legal, então o pool é hidratado antes da ordenação.
    hydrated_pool = False
    try:
        pool = list(candidates)
        if deps.rescore is not None:
            pool = hydrate(pool[: deps.settings.rerank_pool], repo=deps.repo).devices
            hydrated_pool = True
        ranked = rerank(
            plan.consulta_juridica,
            pool,
            encoder=deps.rerank_encoder,
            top_k=deps.settings.max_devices,
            rescore=deps.rescore,
        )
        selected = dedupe_by_artigo(ranked, max_per_article=deps.settings.max_devices_per_article)[
            : deps.settings.max_devices
        ]
    except Exception:
        return _abstain_rec(plan, "erro_recuperacao")

    try:
        hydrated = selected if hydrated_pool else hydrate(selected, repo=deps.repo).devices
    except Exception:
        return _abstain_rec(plan, "erro_recuperacao")
    if not hydrated:
        return _abstain_rec(plan, "contexto_incompleto")

    expanded = expand_devices(hydrated, deps)
    return Recuperacao(
        plan.fatos,
        tuple(plan.subperguntas),
        devices=tuple(expanded),
        retrieved_ids=tuple(item.device_id for item in expanded),
    )


# --------------------------------------------------------------------------- helpers movidos
def _abstain_rec(plan: QueryPlan, motivo: str) -> Recuperacao:
    return Recuperacao(plan.fatos, tuple(plan.subperguntas), abstencao=motivo)


def with_extracted_data_fato(message: str, facts: QueryFacts | None) -> QueryFacts | None:
    """Preenche a data do fato ausente a partir da pergunta; nunca sobrepõe o cliente."""

    if facts is not None and facts.data_fato is not None:
        return facts
    extracted = extract_data_fato(message)
    if extracted is None:
        return facts
    base = facts if facts is not None else default_facts()
    return base.model_copy(update={"data_fato": extracted})


def explicit_devices(
    resolution: CitationResolution,
    facts: QueryFacts | None,
    deps: DepsRecuperacao,
) -> list[RetrievedDevice]:
    device_id = resolution.device_id
    if device_id is None:
        return []
    getter = getattr(deps.repo, "get_current_version_id", None)
    if getter is None:
        return []
    version = getter(device_id, facts.data_fato if facts else None)
    if version is None:
        return []
    hydrated = hydrate([(device_id, int(version))], repo=deps.repo).devices
    explicit = [item.model_copy(update={"source": "explicit"}) for item in hydrated]
    return expand_devices(explicit, deps)


def expand_devices(
    devices: Sequence[RetrievedDevice], deps: DepsRecuperacao
) -> list[RetrievedDevice]:
    if not hasattr(deps.repo, "lookup"):
        return list(devices)
    try:
        return expand_to_article(devices, article_lookup=deps.repo).devices
    except Exception:
        return list(devices)


def is_explicit_miss(resolution: CitationResolution) -> bool:
    if resolution.ambiguous:
        return True
    return resolution.reason in {
        "not_found",
        "no_catalog",
        "article_missing",
        "norm_ambiguous",
    }
