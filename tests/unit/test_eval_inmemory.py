from __future__ import annotations

import json
from datetime import date

import pytest

from src.config import Settings
from src.eval.inmemory import (
    BM25FtsSearcher,
    GoldContextPipeline,
    InMemoryRepo,
    NumpyDenseSearcher,
    build_benchmark_pipeline,
    dedupe_corpus_rows,
    load_corpus,
)
from src.generate.llm import MockLLM


def _row(
    device_id: str,
    *,
    version: int = 1,
    status: str = "vigente",
    inicio: str = "2020-01-01",
    fim: str | None = None,
    texto: str = "Texto do dispositivo.",
    search_text: str = "texto dispositivo",
    artigo_id: str | None = None,
) -> dict:
    return {
        "device_id": device_id,
        "norm_version_id": version,
        "norm_id": device_id.split("/")[0],
        "artigo_id": artigo_id or device_id,
        "tipo": "artigo",
        "parent_id": None,
        "rotulo": "Art. 1",
        "caminho": "Título I > Art. 1",
        "texto_literal": texto,
        "contexto": "Contexto",
        "citacao": f"Citacao {device_id}",
        "vigencia_status": status,
        "vigencia_inicio": inicio,
        "vigencia_fim": fim,
        "fonte_url": "https://example.test",
        "search_text": search_text,
        "qdrant_point_id": "00000000-0000-0000-0000-000000000001",
        "content_hash": "hash",
    }


class _FixedEncoder:
    dimension = 2
    model_name = "fixed"
    revision = "fixed"

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def encode_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="mock",
        embedding_provider="harrier",
        retrieval_path="fallback",
        max_devices=10,
        max_context_tokens=6000,
    )


def test_load_corpus_reads_jsonl_and_skips_blank(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        json.dumps(_row("lmp/art1")) + "\n\n" + json.dumps(_row("lmp/art2")) + "\n",
        encoding="utf-8",
    )

    rows = load_corpus([path])

    assert [row["device_id"] for row in rows] == ["lmp/art1", "lmp/art2"]


def test_repo_selects_version_in_force_on_the_fact_date():
    rows = [
        _row("lmp/art1", version=1, inicio="2006-08-07"),
        _row("lmp/art1", version=2, status="alterado", inicio="2024-01-01"),
        _row(
            "lmp/art1",
            version=3,
            status="revogado",
            inicio="2025-01-01",
            fim="2025-12-31",
        ),
    ]
    repo = InMemoryRepo(rows)

    assert repo.get_current_version_id("lmp/art1", date(2010, 1, 1)) == 1
    assert repo.get_current_version_id("lmp/art1", date(2026, 1, 1)) == 2
    assert repo.get_device_version_on("lmp/art1", date(2026, 1, 1))["norm_version_id"] == 2


def test_repo_does_not_return_an_expired_version():
    rows = [
        _row("lmp/art1", version=1, inicio="2006-08-07", fim="2019-12-31"),
        _row("lmp/art1", version=2, inicio="2020-01-01", fim="2025-12-31"),
    ]
    repo = InMemoryRepo(rows)

    assert repo.get_current_version_id("lmp/art1", date(2026, 1, 1)) is None
    assert repo.get_device_version("lmp/art1", 2)["norm_version_id"] == 2


def test_dense_search_orders_by_cosine_and_respects_vigencia():
    rows = [
        _row("lmp/art1"),
        _row("lmp/art2", fim="2020-12-31"),
        _row("lmp/art3"),
    ]
    vectors = {
        ("lmp/art1", 1): [1.0, 0.0],
        ("lmp/art2", 1): [0.9, 0.1],
        ("lmp/art3", 1): [0.0, 1.0],
    }
    searcher = NumpyDenseSearcher(rows, vectors, _FixedEncoder())

    hits = searcher.search("prazo", limit=2, data_fato=date(2026, 1, 1))

    assert [hit.device_id for hit in hits] == ["lmp/art1", "lmp/art3"]
    assert hits[0].source == "dense"
    assert hits[0].score > hits[1].score


def test_bm25_search_ranks_lexical_match_first():
    rows = [
        _row("lmp/art1", search_text="prazo para denunciar violencia domestica"),
        _row("lmp/art2", search_text="divorcio no exterior guarda compartilhada"),
    ]
    searcher = BM25FtsSearcher(rows)

    hits = searcher.search("prazo denunciar", limit=2)

    assert [hit.device_id for hit in hits] == ["lmp/art1"]
    assert hits[0].source == "bm25"


def test_hybrid_pipeline_returns_retrieved_ids():
    rows = [
        _row("lmp/art1", texto="Prazo para denunciar violência doméstica."),
        _row("lmp/art2", texto="Divórcio no exterior."),
    ]
    vectors = {("lmp/art1", 1): [1.0, 0.0], ("lmp/art2", 1): [0.0, 1.0]}
    pipeline = build_benchmark_pipeline(
        rows=rows,
        vectors=vectors,
        encoder=_FixedEncoder(),
        settings=_settings(),
        llm=MockLLM(),
        mode="hybrid",
    )

    result = pipeline.answer("Qual o prazo para denunciar?")

    assert result.retrieved_ids
    assert "lmp/art1" in result.retrieved_ids


def test_gold_pipeline_uses_only_the_gold_devices():
    rows = [
        _row("lmp/art1", texto="Prazo de 12 meses para denunciar."),
        _row("lmp/art2", texto="Outro dispositivo."),
    ]
    pipeline = GoldContextPipeline(
        repo=InMemoryRepo(rows),
        settings=_settings(),
        llm=MockLLM(),
        gold_by_question={"Qual o prazo?": ["lmp/art1"]},
    )

    result = pipeline.answer("Qual o prazo?")

    assert result.retrieved_ids == ("lmp/art1",)
    assert result.answer.citacoes[0].device_id == "lmp/art1"


def test_build_benchmark_pipeline_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown benchmark mode"):
        build_benchmark_pipeline(
            rows=[],
            vectors={},
            encoder=_FixedEncoder(),
            settings=_settings(),
            llm=MockLLM(),
            mode="nope",
        )


def test_repo_dated_lookup_keeps_revoked_version_in_force_but_current_lookup_excludes_it():
    rows = [
        _row("lmp/art1", version=1, status="revogado", inicio="2020-01-01", fim="2025-12-31"),
    ]
    repo = InMemoryRepo(rows)

    assert repo.get_device_version_on("lmp/art1", date(2024, 1, 1)) is not None
    assert repo.get_current_version_id("lmp/art1", date(2024, 1, 1)) is None


def test_dense_search_with_explicit_date_includes_revoked_version():
    rows = [
        _row("lmp/art1", status="revogado", inicio="2020-01-01", fim="2025-12-31"),
        _row("lmp/art2", inicio="2020-01-01"),
    ]
    vectors = {("lmp/art1", 1): [1.0, 0.0], ("lmp/art2", 1): [0.0, 1.0]}
    searcher = NumpyDenseSearcher(rows, vectors, _FixedEncoder())

    dated = searcher.search("prazo", limit=2, data_fato=date(2024, 1, 1))
    current = searcher.search("prazo", limit=2, data_fato=None)

    assert "lmp/art1" in [hit.device_id for hit in dated]
    assert "lmp/art1" not in [hit.device_id for hit in current]


def test_bm25_normalizes_accents_in_the_query():
    rows = [_row("lmp/art1", search_text="violencia domestica e medida protetiva")]
    searcher = BM25FtsSearcher(rows)

    hits = searcher.search("violência doméstica", limit=1)

    assert [hit.device_id for hit in hits] == ["lmp/art1"]


def test_dedupe_corpus_rows_prefers_the_latest_vigencia():
    rows = [
        _row("lmp/art1", version=1, inicio="2020-01-01", texto="antigo"),
        _row("lmp/art1", version=1, inicio="2024-01-01", texto="novo"),
    ]

    deduped = dedupe_corpus_rows(rows)

    assert len(deduped) == 1
    assert deduped[0]["texto_literal"] == "novo"
