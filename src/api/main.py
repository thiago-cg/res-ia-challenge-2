"""FastAPI surface for the legal RAG prototype (GEN-05).

The app is wired through dependency injection so tests can run without a
database, Qdrant or an external LLM.  ``create_app`` receives an optional
pipeline, source repository and health probe; the module-level ``app`` only
builds lazy adapters that connect on first use.

Serve with ``uvicorn --no-access-log``: request correlation and a body-free
access event are already emitted by ``RequestContextMiddleware``, while
uvicorn's access log would record query strings.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request

from src.api.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_error_handlers,
)
from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SourceResponse,
    legal_notice,
)
from src.config import Settings, get_settings
from src.contracts import (
    Answer,
    Citation,
    CitationResolution,
    InvalidCitation,
    QueryFacts,
    RetrievedDevice,
)
from src.generate.fallback import abstain as fallback_abstain
from src.generate.fallback import build_safe_answer
from src.generate.llm import LLMClient, get_llm
from src.generate.prompt import SYSTEM_PROMPT, build_user_prompt
from src.generate.schemas import LLMOutput, LLMOutputError, parse_llm_output
from src.generate.verify import verify
from src.index.embed import Encoder, get_encoder
from src.index.pgvector import dense_search, fts_search
from src.index.qdrant import QdrantDenseSearcher
from src.obs.logging import configure_logging
from src.retrieve.citations import CitationCatalog, resolve_explicit_citation
from src.retrieve.expand import artigo_id, dedupe_by_artigo, expand_to_article
from src.retrieve.hybrid import DenseSearcher, FtsSearcher, QdrantSearcher, hybrid_search
from src.retrieve.hydrate import hydrate, resolve_citation
from src.retrieve.query import default_facts, extract_data_fato, understand_query
from src.retrieve.rerank import MultiVectorEncoder, Rescore, rerank
from src.safety.risk import classify_risk, emergency_answer

logger = logging.getLogger(__name__)

_VERSION_QUERY = Query(default=None, gt=0)
_DATE_QUERY = Query(default=None, alias="date")


@dataclass(frozen=True)
class PipelineResult:
    answer: Answer
    emergencia: bool = False
    data_atualizacao_base: str | None = None
    retrieved_ids: tuple[str, ...] = ()
    claims_supported: tuple[bool, ...] = ()


class ChatPipeline(Protocol):
    def answer(self, message: str, facts: QueryFacts | None = None) -> PipelineResult: ...


class HealthProbe(Protocol):
    def snapshot(self) -> dict[str, Any]: ...


class SourceRepo(Protocol):
    def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None: ...

    def get_device_version_on(self, device_id: str, on_date: date) -> Any | None: ...


def health_status(
    *,
    database: str,
    qdrant: str,
    index_version: str | None = None,
    last_ingest: str | None = None,
    data_atualizacao_base: str | None = None,
) -> dict[str, Any]:
    """Never report ``ok`` when a dependency is unreachable."""

    return {
        "status": "ok" if database == "ok" and qdrant == "ok" else "degraded",
        "database": database,
        "qdrant": qdrant,
        "index_version": index_version,
        "last_ingest": last_ingest,
        "data_atualizacao_base": data_atualizacao_base,
    }


class PostgresRepo:
    """Minimal Postgres adapter used by the API wiring.

    Every method opens its own connection; nothing is shared across requests.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None:
        sql = """
            SELECT dv.device_id,
                   dv.norm_version_id,
                   dv.norm_id,
                   dv.texto_literal,
                   dv.contexto,
                   dv.citacao,
                   dv.vigencia_status,
                   dv.vigencia_inicio,
                   dv.vigencia_fim,
                   dv.fonte_url,
                   de.texto AS explicacao
            FROM device_versions dv
            LEFT JOIN device_explanations de
                   ON de.device_id = dv.device_id
                  AND de.norm_version_id = dv.norm_version_id
            WHERE dv.device_id = %s
              AND dv.norm_version_id = %s
        """
        with _open_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (device_id, norm_version_id))
            return cur.fetchone()

    def get_device_version_on(self, device_id: str, on_date: date) -> Any | None:
        sql = """
            SELECT dv.device_id,
                   dv.norm_version_id,
                   dv.norm_id,
                   dv.texto_literal,
                   dv.contexto,
                   dv.citacao,
                   dv.vigencia_status,
                   dv.vigencia_inicio,
                   dv.vigencia_fim,
                   dv.fonte_url,
                   de.texto AS explicacao
            FROM device_versions dv
            LEFT JOIN device_explanations de
                   ON de.device_id = dv.device_id
                  AND de.norm_version_id = dv.norm_version_id
            WHERE dv.device_id = %s
              AND dv.vigencia_inicio <= %s
              AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= %s)
            ORDER BY dv.vigencia_inicio DESC
            LIMIT 1
        """
        with _open_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (device_id, on_date, on_date))
            return cur.fetchone()

    def get_current_version_id(self, device_id: str, data_fato: date | None = None) -> int | None:
        on_date = data_fato or date.today()
        # docs/05 §6: with a fact date the version window alone decides, even
        # when that version is no longer in force today.  Keeping the status
        # filter here made an unambiguous explicit citation of an article that
        # was later revoked abstain instead of returning the text that governed
        # the fact; the retrieval legs already drop the filter in that case.
        status_clause = (
            "" if data_fato is not None else "AND dv.vigencia_status IN ('vigente', 'alterado')"
        )
        sql = f"""
            SELECT dv.norm_version_id
            FROM device_versions dv
            WHERE dv.device_id = %s
              {status_clause}
              AND dv.vigencia_inicio <= %s
              AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= %s)
            ORDER BY dv.vigencia_inicio DESC
            LIMIT 1
        """
        with _open_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (device_id, on_date, on_date))
            row = cur.fetchone()
        if row is None:
            return None
        return int(row["norm_version_id"])

    def find(self, norm_id: str, artigo_id: str) -> Any | None:
        sql = """
            SELECT d.id AS device_id, d.norm_id, d.artigo_id
            FROM devices d
            WHERE d.norm_id = %s
              AND d.id = %s
              AND EXISTS (
                  SELECT 1 FROM device_versions dv WHERE dv.device_id = d.id
              )
            ORDER BY d.id
            LIMIT 1
        """
        with _open_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (norm_id, artigo_id))
            return cur.fetchone()

    def lookup(self, artigo_id: str, norm_version_id: int) -> Any | None:
        sql = """
            SELECT device_id, norm_version_id, texto_literal, contexto
            FROM device_versions
            WHERE device_id = %s
              AND norm_version_id = %s
        """
        with _open_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (artigo_id, norm_version_id))
            return cur.fetchone()

    def health_snapshot(self) -> tuple[str, str | None, str | None]:
        sql = """
            SELECT (SELECT max(norm_version_id) FROM device_versions) AS index_version,
                   (SELECT max(finished_at) FROM ingest_runs WHERE status = 'ok')
                       AS last_ingest
        """
        with _open_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone() or {}
        return "ok", _as_text(row.get("index_version")), _as_text(row.get("last_ingest"))

    def get_data_atualizacao_base(self) -> str | None:
        try:
            _, _, last_ingest = self.health_snapshot()
        except Exception:
            return None
        if not last_ingest:
            return None
        return last_ingest[:10]


class PgDenseSearcher:
    def __init__(self, database_url: str, encoder: Encoder) -> None:
        self.database_url = database_url
        self.encoder = encoder

    def search(self, query: str, limit: int, data_fato: date | None = None) -> list[Any]:
        vector = _flat_vector(self.encoder.encode_query(query))
        with _open_connection(self.database_url) as conn:
            return list(dense_search(conn, vector, limit=limit, data_fato=data_fato))


class PgFtsSearcher:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def search(self, query: str, limit: int, data_fato: date | None = None) -> list[Any]:
        with _open_connection(self.database_url) as conn:
            return list(fts_search(conn, query, limit=limit, data_fato=data_fato))


class SettingsHealthProbe:
    """Default probe; every dependency is checked and reported honestly."""

    def __init__(
        self,
        settings: Settings,
        *,
        repo: Any | None = None,
        data_atualizacao_base: str | None = None,
        database_check: Callable[[], tuple[str, str | None, str | None]] | None = None,
        qdrant_check: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.data_atualizacao_base = data_atualizacao_base
        self._database_check = database_check
        self._qdrant_check = qdrant_check

    def snapshot(self) -> dict[str, Any]:
        database = "unavailable"
        index_version: str | None = None
        last_ingest: str | None = None

        if self._database_check is not None:
            database, index_version, last_ingest = self._database_check()
        elif self.repo is not None:
            try:
                database, index_version, last_ingest = self.repo.health_snapshot()
            except Exception:
                database = "unavailable"

        qdrant = self._qdrant_check() if self._qdrant_check is not None else self._check_qdrant()
        data_atualizacao_base = self.data_atualizacao_base
        if data_atualizacao_base is None and last_ingest:
            data_atualizacao_base = last_ingest[:10]
        return health_status(
            database=database,
            qdrant=qdrant,
            index_version=index_version,
            last_ingest=last_ingest,
            data_atualizacao_base=data_atualizacao_base,
        )

    def _check_qdrant(self) -> str:
        try:
            import httpx

            response = httpx.get(
                f"{self.settings.qdrant_url.rstrip('/')}/collections",
                timeout=2.0,
            )
        except Exception:
            return "unavailable"
        return "ok" if response.status_code < 400 else "unavailable"


class LegalRAGPipeline:
    """Orchestrates risk routing, retrieval, generation and verification."""

    def __init__(
        self,
        *,
        repo: Any,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        dense: DenseSearcher | None = None,
        fts: FtsSearcher | None = None,
        qdrant: QdrantSearcher | None = None,
        encoder: Encoder | MultiVectorEncoder | None = None,
        rescore: Rescore | None = None,
        judge: Callable[..., Any] | None = None,
        catalog: CitationCatalog | None = None,
        data_atualizacao_base: str | None = None,
    ) -> None:
        self.repo = repo
        self.settings = settings or get_settings()
        self._llm = llm
        self.dense = dense
        self.fts = fts
        self.qdrant = qdrant
        self.encoder = encoder
        self.rescore = rescore
        self.judge = judge
        self.catalog = catalog if catalog is not None else _catalog_from(repo)
        self._data_atualizacao_base = data_atualizacao_base
        self._data_atualizacao_checked = data_atualizacao_base is not None

    @property
    def data_atualizacao_base(self) -> str | None:
        """Resolve the base date lazily so emergency answers touch no storage."""

        if not self._data_atualizacao_checked:
            self._data_atualizacao_checked = True
            getter = getattr(self.repo, "get_data_atualizacao_base", None)
            if callable(getter):
                try:
                    self._data_atualizacao_base = getter()
                except Exception:
                    logger.warning("data_atualizacao_unavailable")
        return self._data_atualizacao_base

    def answer(self, message: str, facts: QueryFacts | None = None) -> PipelineResult:
        if classify_risk(message).immediate:
            return self._result(emergency_answer(), emergencia=True)

        facts = self._with_extracted_data_fato(message, facts)

        try:
            resolution = resolve_explicit_citation(
                message,
                catalog=self.catalog,
                data_fato=facts.data_fato if facts else None,
            )
        except Exception as exc:
            logger.warning("explicit_citation_failed error=%s", type(exc).__name__)
            return self._abstain("erro_recuperacao")

        if resolution.resolved:
            try:
                explicit = self._explicit_devices(resolution, facts)
            except Exception as exc:
                logger.warning("explicit_hydration_failed error=%s", type(exc).__name__)
                return self._abstain("erro_recuperacao")
            if not explicit:
                return self._abstain("citacao_explicita_sem_versao_vigente")
            return self._generate(message, facts or default_facts(), [message], explicit)

        if self._is_explicit_miss(resolution):
            return self._abstain("citacao_explicita_nao_encontrada")

        plan = understand_query(
            message,
            facts,
            max_subquestions=self.settings.max_subquestions,
            expand=self.settings.query_expansion,
        )
        try:
            candidates = hybrid_search(
                plan,
                dense=self.dense,
                fts=self.fts,
                qdrant=self.qdrant,
                path=self.settings.retrieval_path,
                data_fato=plan.fatos.data_fato,
                lexical_weight=self.settings.hybrid_lexical_weight,
            )
        except Exception as exc:
            logger.warning("retrieval_failed error=%s", type(exc).__name__)
            return self._abstain("falha_na_recuperacao")

        if not candidates:
            return self._abstain("nenhum_dispositivo_recuperado")

        # A reranker has to read the legal text, so the pool is hydrated before
        # ranking; without that it would order candidates by their id alone.
        hydrated_pool = False
        try:
            pool = list(candidates)
            if self.rescore is not None:
                pool = hydrate(pool[: self.settings.rerank_pool], repo=self.repo).devices
                hydrated_pool = True
            ranked = rerank(
                plan.consulta_juridica,
                pool,
                encoder=_as_rerank_encoder(self.encoder),
                top_k=self.settings.max_devices,
                rescore=self.rescore,
            )
            selected = dedupe_by_artigo(
                ranked, max_per_article=self.settings.max_devices_per_article
            )[: self.settings.max_devices]
        except Exception as exc:
            logger.warning("ranking_failed error=%s", type(exc).__name__)
            return self._abstain("erro_recuperacao")

        try:
            hydrated = selected if hydrated_pool else hydrate(selected, repo=self.repo).devices
        except Exception as exc:
            logger.warning("hydration_failed error=%s", type(exc).__name__)
            return self._abstain("erro_recuperacao")
        if not hydrated:
            return self._abstain("contexto_incompleto")
        expanded = self._expand(hydrated)
        return self._generate(message, plan.fatos, plan.subperguntas, expanded)

    @staticmethod
    def _with_extracted_data_fato(message: str, facts: QueryFacts | None) -> QueryFacts | None:
        """Fill a missing fact date from the question; never override the client."""

        if facts is not None and facts.data_fato is not None:
            return facts
        extracted = extract_data_fato(message)
        if extracted is None:
            return facts
        base = facts if facts is not None else default_facts()
        return base.model_copy(update={"data_fato": extracted})

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = get_llm(self.settings)
        return self._llm

    def _explicit_devices(
        self, resolution: CitationResolution, facts: QueryFacts | None
    ) -> list[RetrievedDevice]:
        device_id = resolution.device_id
        if device_id is None:
            return []
        getter = getattr(self.repo, "get_current_version_id", None)
        if getter is None:
            return []
        version = getter(device_id, facts.data_fato if facts else None)
        if version is None:
            return []
        hydrated = hydrate([(device_id, int(version))], repo=self.repo).devices
        explicit = [item.model_copy(update={"source": "explicit"}) for item in hydrated]
        return self._expand(explicit)

    def _expand(self, devices: list[RetrievedDevice]) -> list[RetrievedDevice]:
        if not hasattr(self.repo, "lookup"):
            return devices
        try:
            return expand_to_article(devices, article_lookup=self.repo).devices
        except Exception as exc:
            logger.warning("article_expansion_skipped error=%s", type(exc).__name__)
            return devices

    @staticmethod
    def _is_explicit_miss(resolution: CitationResolution) -> bool:
        if resolution.ambiguous:
            return True
        return resolution.reason in {
            "not_found",
            "no_catalog",
            "article_missing",
            "norm_ambiguous",
        }

    def _generate(
        self,
        message: str,
        fatos: QueryFacts,
        subperguntas: Sequence[str],
        retrieved: Sequence[RetrievedDevice],
    ) -> PipelineResult:
        if not retrieved:
            return self._abstain("contexto_incompleto")

        retrieved_ids = tuple(item.device_id for item in retrieved)
        prompt = build_user_prompt(
            message,
            fatos,
            list(subperguntas),
            retrieved,
            max_devices=self.settings.max_devices,
            max_context_tokens=self.settings.max_context_tokens,
        )

        for attempt in (1, 2):
            try:
                raw = self._complete(prompt, retrieved)
            except Exception as exc:
                logger.warning("llm_unavailable error=%s", type(exc).__name__)
                return self._safe_answer(retrieved, "llm_indisponivel")

            try:
                output = parse_llm_output(
                    raw,
                    allowed_ids={item.device_id for item in retrieved},
                )
            except LLMOutputError as exc:
                if attempt == 1:
                    prompt = self._feedback_prompt(prompt, str(exc))
                    continue
                logger.warning("llm_output_rejected")
                return self._safe_answer(retrieved, "saida_invalida")

            if output.abstencao:
                reason = output.motivo_abstencao or "abstencao_do_modelo"
                return self._result(
                    fallback_abstain(
                        reason,
                        retrieved=retrieved,
                        data_atualizacao=self.data_atualizacao_base,
                    ),
                    emergencia=False,
                    retrieved_ids=retrieved_ids,
                )

            try:
                answer = self._render_answer(output, retrieved)
            except InvalidCitation as exc:
                if attempt == 1:
                    prompt = self._feedback_prompt(prompt, str(exc))
                    continue
                return self._safe_answer(retrieved, "citacao_invalida")
            except Exception as exc:
                logger.warning("citation_render_failed error=%s", type(exc).__name__)
                return self._abstain("erro_recuperacao", retrieved_ids=retrieved_ids)

            try:
                verification = verify(
                    answer,
                    retrieved,
                    repo=self.repo,
                    judge=self.judge,
                    attempt=attempt,
                    max_attempts=2,
                )
            except Exception as exc:
                logger.warning("verification_failed error=%s", type(exc).__name__)
                return self._abstain("erro_recuperacao", retrieved_ids=retrieved_ids)
            if verification.action == "accept":
                return self._result(
                    answer,
                    emergencia=False,
                    retrieved_ids=retrieved_ids,
                    claims_supported=verification.claims_supported,
                )
            if verification.action == "regenerate" and attempt == 1:
                prompt = self._feedback_prompt(prompt, "; ".join(verification.issues))
                continue
            return self._abstain("verificacao_falhou", retrieved_ids=retrieved_ids)

        return self._safe_answer(retrieved, "nao_foi_possivel_gerar")

    def _render_answer(self, output: LLMOutput, retrieved: Sequence[RetrievedDevice]) -> Answer:
        by_id: dict[str, RetrievedDevice] = {}
        for candidate in retrieved:
            by_id.setdefault(candidate.device_id, candidate)

        citations: list[Citation] = []
        seen: set[tuple[str, int]] = set()
        for cited in output.citacoes:
            device = by_id.get(cited.device_id)
            if device is None:
                raise InvalidCitation(f"device_id não recuperado: {cited.device_id}")
            pair = (device.device_id, device.norm_version_id)
            if pair in seen:
                continue
            seen.add(pair)
            citation = resolve_citation(device.device_id, device.norm_version_id, repo=self.repo)
            citations.append(citation.model_copy(update={"afirmacao": cited.afirmacao}))

        citations.extend(self._ancestor_citations(citations, by_id, seen))

        return Answer(
            resposta=output.resposta,
            citacoes=citations,
            proximos_passos=list(output.proximos_passos),
            encaminhamentos=[dict(referral) for referral in output.encaminhamentos],
            premissas=list(output.premissas),
            nivel_confianca=output.nivel_confianca,
            abstencao=output.abstencao,
            motivo_abstencao=output.motivo_abstencao,
        )

    def _ancestor_citations(
        self,
        citations: Sequence[Citation],
        by_id: dict[str, RetrievedDevice],
        seen: set[tuple[str, int]],
    ) -> list[Citation]:
        """Also cite the article row when the model cited one of its devices.

        The model cites the device it actually read, which is often a paragraph,
        an inciso or the /cpt duplicate.  When the article row is present in the
        context it is the same norm and the answer relies on it too, so the
        citation list should carry it; nothing is added when the article is not
        in the retrieved context.
        """

        extra: list[Citation] = []
        for citation in list(citations):
            ancestor = artigo_id(citation.device_id)
            if ancestor == citation.device_id:
                continue
            device = by_id.get(ancestor)
            if device is None:
                continue
            pair = (device.device_id, device.norm_version_id)
            if pair in seen:
                continue
            seen.add(pair)
            resolved = resolve_citation(device.device_id, device.norm_version_id, repo=self.repo)
            extra.append(resolved.model_copy(update={"afirmacao": citation.afirmacao}))
        return extra

    def _complete(self, prompt: str, retrieved: Sequence[RetrievedDevice]) -> str:
        llm = self.llm
        setter = getattr(llm, "set_context_ids", None)
        if callable(setter):
            setter([item.device_id for item in retrieved])
        return llm.complete(SYSTEM_PROMPT, prompt)

    @staticmethod
    def _feedback_prompt(prompt: str, feedback: str) -> str:
        return (
            f"{prompt}\n\n[FEEDBACK DA VERIFICAÇÃO]\n{feedback}\n"
            "Corrija a saída. Use apenas device_id do contexto e devolva apenas "
            "o JSON do schema."
        )

    def _safe_answer(self, retrieved: Sequence[RetrievedDevice], reason: str) -> PipelineResult:
        return PipelineResult(
            build_safe_answer(retrieved, reason),
            False,
            self.data_atualizacao_base,
            tuple(item.device_id for item in retrieved),
        )

    def _abstain(self, reason: str, *, retrieved_ids: Sequence[str] = ()) -> PipelineResult:
        return PipelineResult(
            fallback_abstain(reason, data_atualizacao=self.data_atualizacao_base),
            False,
            self.data_atualizacao_base,
            tuple(retrieved_ids),
        )

    def _result(
        self,
        answer: Answer,
        *,
        emergencia: bool,
        retrieved_ids: Sequence[str] = (),
        claims_supported: Sequence[bool] = (),
    ) -> PipelineResult:
        data = self._data_atualizacao_base if emergencia else self.data_atualizacao_base
        return PipelineResult(
            answer,
            emergencia,
            data,
            tuple(retrieved_ids),
            tuple(claims_supported),
        )


class LazyChatPipeline:
    def __init__(self, factory: Callable[[], ChatPipeline]) -> None:
        self._factory = factory
        self._pipeline: ChatPipeline | None = None

    def answer(self, message: str, facts: QueryFacts | None = None) -> PipelineResult:
        if classify_risk(message).immediate:
            return PipelineResult(emergency_answer(), True, None)

        pipeline = self._pipeline
        if pipeline is None:
            try:
                pipeline = self._factory()
            except Exception as exc:
                logger.error("pipeline_unavailable error=%s", type(exc).__name__)
                return PipelineResult(fallback_abstain("servico_indisponivel"), False, None)
            self._pipeline = pipeline
        return pipeline.answer(message, facts)


def _as_rerank_encoder(
    encoder: Encoder | MultiVectorEncoder | None,
) -> MultiVectorEncoder | None:
    """Rerank needs token multivectors; dense encoders keep the RRF order."""

    if encoder is None:
        return None
    if callable(getattr(encoder, "encode_document", None)):
        return cast(MultiVectorEncoder, encoder)
    return None


def build_default_pipeline(
    settings: Settings, data_atualizacao_base: str | None
) -> LegalRAGPipeline:
    repo = PostgresRepo(settings.database_url)
    dense: DenseSearcher | None = None
    fts: FtsSearcher | None = None
    encoder: Encoder | None = None

    if settings.embedding_provider == "openrouter" and settings.retrieval_path == "target":
        raise ValueError(
            "EMBEDDING_PROVIDER=openrouter has no multivector/late-interaction model; "
            "the pplx-embed-v2-late models are not available on OpenRouter. "
            "Use RETRIEVAL_PATH=fallback with OpenRouter."
        )
    if settings.retrieval_path == "target":
        raise ValueError(
            "target retrieval path requires an injected qdrant searcher; "
            "use create_app(pipeline=...) in that configuration"
        )
    if settings.retrieval_path == "fallback":
        encoder = get_encoder(settings)
        if settings.dense_backend == "qdrant":
            dense = QdrantDenseSearcher(settings.qdrant_url, encoder)
        else:
            dense = PgDenseSearcher(settings.database_url, encoder)
        fts = PgFtsSearcher(settings.database_url)

    rescore = None
    if settings.rerank_provider == "llm":
        from src.retrieve.llm_rerank import LazyLLM, LLMReranker

        rescore = LLMReranker(
            LazyLLM(settings, settings.rerank_model or None),
            pool=settings.rerank_pool,
            max_tokens=settings.rerank_max_tokens,
        )

    return LegalRAGPipeline(
        repo=repo,
        settings=settings,
        dense=dense,
        fts=fts,
        encoder=encoder,
        rescore=rescore,
        data_atualizacao_base=data_atualizacao_base,
    )


def build_eval_pipeline() -> Callable[[Mapping[str, Any]], Any]:
    """Build the real pipeline adapter consumed by ``src.eval.run``.

    The evaluation CLI reports the ``RuntimeError`` below when Postgres or the
    encoder is unavailable, instead of failing one question at a time. The
    encoder is probed once, during this call only, so a missing model artifact
    does not silently degrade every question into an abstention.
    """

    from src.eval.pipeline import make_eval_pipeline

    try:
        settings = get_settings()
        pipeline = build_default_pipeline(settings, None)
        checker = getattr(pipeline.repo, "health_snapshot", None)
        if callable(checker):
            checker()
        dense_checker = getattr(pipeline, "dense", None)
        if dense_checker is not None and hasattr(dense_checker, "health_snapshot"):
            dense_checker.health_snapshot()
    except Exception as exc:
        raise RuntimeError(
            "pipeline real de avaliação indisponível: não foi possível montar "
            "Postgres/encoder. Verifique DATABASE_URL, EMBEDDING_MODEL_REVISION e o "
            "extra 'ml'; modelos GGUF não são suportados, o caminho exige safetensors "
            "e, sem GPU, use RETRIEVAL_PATH=fallback. "
            f"Detalhe: {type(exc).__name__}: {exc}"
        ) from exc
    _probe_eval_encoder(settings, getattr(pipeline, "encoder", None))
    return make_eval_pipeline(pipeline)


def _probe_eval_encoder(settings: Settings, encoder: Any) -> None:
    """Fail fast when the configured encoder cannot produce an embedding."""

    if encoder is None:
        raise RuntimeError(
            "pipeline real de avaliação indisponível: o pipeline não expôs encoder. "
            "Use RETRIEVAL_PATH=fallback com um encoder Harrier configurado."
        )

    configured_revision = getattr(settings, "embedding_model_revision", "")
    revision = str(getattr(encoder, "revision", None) or configured_revision)
    if not revision or revision.lower() == "main":
        raise RuntimeError(
            "pipeline real de avaliação indisponível: EMBEDDING_MODEL_REVISION deve "
            "estar pinado em um commit/tag; vazio ou 'main' não serve."
        )

    configured_path = _encoder_model_path(settings)
    if configured_path:
        model_path = Path(configured_path)
        if not model_path.exists():
            raise RuntimeError(
                "pipeline real de avaliação indisponível: caminho do modelo não existe: "
                f"{model_path}. Aponte para um diretório safetensors válido ou use "
                "RETRIEVAL_PATH=fallback."
            )
        if model_path.suffix.lower() == ".gguf":
            raise RuntimeError(
                "pipeline real de avaliação indisponível: GGUF (llama.cpp) não é "
                "suportado; use checkpoints safetensors ou RETRIEVAL_PATH=fallback."
            )

    encode = getattr(encoder, "encode_query", None)
    if not callable(encode):
        raise RuntimeError(
            "pipeline real de avaliação indisponível: encoder sem encode_query; "
            "use o encoder Harrier do caminho fallback."
        )
    try:
        encode("probe")
    except Exception as exc:
        raise RuntimeError(
            "pipeline real de avaliação indisponível: o encoder não gerou o embedding "
            "de teste. Use checkpoints safetensors (GGUF/llama.cpp não é suportado), "
            "confira EMBEDDING_MODEL_REVISION e os caminhos de modelo; sem GPU, use "
            "RETRIEVAL_PATH=fallback. "
            f"Detalhe: {type(exc).__name__}: {exc}"
        ) from exc


def _encoder_model_path(settings: Settings) -> str | None:
    provider = getattr(settings, "embedding_provider", "harrier")
    if provider == "openrouter":
        return None
    if provider == "harrier":
        return getattr(settings, "harrier_model_path", "") or None
    if getattr(settings, "retrieval_path", "fallback") == "target":
        return getattr(settings, "ppx_9b_model_path", "") or None
    return getattr(settings, "ppx_06b_model_path", "") or None


def create_app(
    *,
    settings: Settings | None = None,
    pipeline: ChatPipeline | None = None,
    source_repo: SourceRepo | None = None,
    health_probe: HealthProbe | None = None,
    data_atualizacao_base: str | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level)
    repo: Any = source_repo or PostgresRepo(settings.database_url)
    probe = health_probe or SettingsHealthProbe(
        settings,
        repo=repo,
        data_atualizacao_base=data_atualizacao_base,
    )
    resolved_pipeline = pipeline or LazyChatPipeline(
        lambda: build_default_pipeline(settings, data_atualizacao_base)
    )

    app = FastAPI(
        title="Orientação jurídica — violência doméstica",
        version="0.1.0",
        description=legal_notice(data_atualizacao_base),
    )
    app.state.settings = settings
    app.state.pipeline = resolved_pipeline
    app.state.source_repo = repo
    app.state.health_probe = probe
    app.state.data_atualizacao_base = data_atualizacao_base

    install_error_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.post("/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, http_request: Request) -> ChatResponse:
        request_id = getattr(http_request.state, "request_id", None) or uuid4().hex
        logger.info(
            "chat_request request_id=%s session_id=%s",
            request_id,
            payload.session_id,
        )
        if classify_risk(payload.message).immediate:
            response = ChatResponse.from_answer(
                emergency_answer(),
                emergencia=True,
                data_atualizacao_base=http_request.app.state.data_atualizacao_base,
            )
            logger.info(
                "chat_response request_id=%s abstencao=%s emergencia=%s citacoes=%d",
                request_id,
                response.abstencao,
                response.emergencia,
                len(response.citacoes),
            )
            return response

        try:
            result = http_request.app.state.pipeline.answer(
                payload.message,
                payload.query_facts(),
            )
        except Exception as exc:
            logger.error("chat_failure request_id=%s error=%s", request_id, type(exc).__name__)
            raise HTTPException(
                status_code=500,
                detail="Não foi possível processar a solicitação agora.",
            ) from None

        data_atualizacao = (
            result.data_atualizacao_base
            if result.data_atualizacao_base is not None
            else http_request.app.state.data_atualizacao_base
        )
        response = ChatResponse.from_answer(
            result.answer,
            emergencia=result.emergencia,
            data_atualizacao_base=data_atualizacao,
        )
        logger.info(
            "chat_response request_id=%s abstencao=%s emergencia=%s citacoes=%d",
            request_id,
            response.abstencao,
            response.emergencia,
            len(response.citacoes),
        )
        return response

    @app.get("/health", response_model=HealthResponse)
    def health(http_request: Request) -> HealthResponse:
        try:
            snapshot = http_request.app.state.health_probe.snapshot()
        except Exception as exc:
            logger.error("health_probe_failed error=%s", type(exc).__name__)
            snapshot = health_status(
                database="unavailable",
                qdrant="unavailable",
                data_atualizacao_base=http_request.app.state.data_atualizacao_base,
            )
        return HealthResponse(**snapshot)

    @app.get("/sources/{device_id:path}", response_model=SourceResponse)
    def source(
        device_id: str,
        http_request: Request,
        version: int | None = _VERSION_QUERY,
        on_date: date | None = _DATE_QUERY,
    ) -> SourceResponse:
        repo_for_sources = http_request.app.state.source_repo
        try:
            if version is not None:
                row = repo_for_sources.get_device_version(device_id, version)
            else:
                row = repo_for_sources.get_device_version_on(
                    device_id,
                    on_date or date.today(),
                )
        except Exception as exc:
            logger.error("source_lookup_failed error=%s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="Serviço de fontes indisponível.",
            ) from None

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Dispositivo {device_id!r} não encontrado na versão solicitada. "
                    "Confira o device_id, a versão ou a data."
                ),
            )
        return _source_response(row)

    return app


def _source_response(row: Any) -> SourceResponse:
    device_id = _row_field(row, "device_id")
    norm_version_id = _row_field(row, "norm_version_id")
    citacao = _row_field(row, "citacao")
    texto = _row_field(row, "texto_literal")
    if texto is None:
        texto = _row_field(row, "texto")
    vigencia = _row_field(row, "vigencia_status") or _row_field(row, "vigencia")
    fonte_url = _row_field(row, "fonte_url")

    if (
        not device_id
        or norm_version_id is None
        or not citacao
        or texto is None
        or not vigencia
        or not fonte_url
    ):
        raise HTTPException(status_code=500, detail="Metadados incompletos para esta fonte.")

    try:
        return SourceResponse(
            device_id=str(device_id),
            norm_version_id=int(norm_version_id),
            norm_id=_row_field(row, "norm_id"),
            artigo_id=_row_field(row, "artigo_id"),
            citacao=str(citacao),
            texto_literal=str(texto),
            contexto=str(_row_field(row, "contexto") or ""),
            vigencia=vigencia,
            vigencia_inicio=_row_field(row, "vigencia_inicio"),
            vigencia_fim=_row_field(row, "vigencia_fim"),
            fonte_url=str(fonte_url),
        )
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail="Metadados inválidos para esta fonte.",
        ) from None


def _catalog_from(repo: Any) -> CitationCatalog | None:
    finder = getattr(repo, "find", None)
    if finder is None:
        return None
    return repo


def _row_field(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _flat_vector(value: Any) -> list[float]:
    if not value:
        return []
    first = value[0]
    if isinstance(first, (list, tuple)):
        value = first
    return [float(item) for item in value]


@contextmanager
def _open_connection(database_url: str) -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(
        database_url,
        connect_timeout=3,
        row_factory=dict_row,
    ) as conn:
        yield conn


app = create_app()
