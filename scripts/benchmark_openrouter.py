"""Live OpenRouter benchmark over the 20-question evaluation set.

The script never writes the API key or the question text to the report.  It
embeds the parsed corpus once, caches the vectors, then runs the real
``LegalRAGPipeline`` with in-memory storage in three scenarios:

- ``dense``: embeddings only (no lexical list);
- ``hybrid``: dense + BM25 fused with RRF (the production fallback shape);
- ``gold``: gold devices supplied as context, isolating generation quality.

The in-memory adapters are a benchmark harness, not a production fallback: the
BM25 tokenizer is not Postgres Portuguese FTS and the vectors live in RAM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from src.config import get_settings
from src.eval.inmemory import (
    GoldContextPipeline,
    InMemoryRepo,
    build_benchmark_pipeline,
    dedupe_corpus_rows,
    load_corpus,
)
from src.eval.pipeline import make_eval_pipeline
from src.eval.run import EvalQuestion, load_questions, run_eval
from src.generate.llm import get_llm
from src.generate.prompt import PROMPT_VERSION
from src.index.embed import get_encoder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = PROJECT_ROOT / "data" / "eval" / "questions.jsonl"
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "processed"
DEFAULT_SEED = PROJECT_ROOT / "data" / "seed" / "stj-sumulas.jsonl"
DEFAULT_CACHE = PROJECT_ROOT / "data" / "eval" / "cache"
DEFAULT_OUT = PROJECT_ROOT / "data" / "eval" / "benchmark_openrouter.json"
DEFAULT_MD = PROJECT_ROOT / "data" / "eval" / "benchmark_openrouter.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD)
    parser.add_argument(
        "--scenarios",
        default="dense,hybrid,gold",
        help="comma-separated: dense,hybrid,gold",
    )
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="debug: first N questions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenarios = [item.strip() for item in args.scenarios.split(",") if item.strip()]
    unknown = set(scenarios) - {"dense", "hybrid", "gold"}
    if unknown:
        print(f"unknown scenario(s): {sorted(unknown)}", file=sys.stderr)
        return 2

    try:
        questions = load_questions(args.questions)
    except (OSError, ValueError) as exc:
        print(f"could not load questions: {exc}", file=sys.stderr)
        return 2
    if args.limit is not None:
        questions = questions[: args.limit]
    if not questions:
        print("no questions selected", file=sys.stderr)
        return 2

    corpus_paths = sorted(args.corpus.glob("*.jsonl"))
    if args.seed.exists():
        corpus_paths.append(args.seed)
    if not corpus_paths:
        print(f"no corpus JSONL under {args.corpus}", file=sys.stderr)
        return 2

    try:
        rows = _dedupe_rows(load_corpus(corpus_paths))
    except (OSError, ValueError) as exc:
        print(f"could not load corpus: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("corpus is empty", file=sys.stderr)
        return 2

    settings = get_settings()
    if settings.llm_provider != "openrouter" or settings.embedding_provider != "openrouter":
        print(
            "this benchmark requires LLM_PROVIDER=openrouter and "
            "EMBEDDING_PROVIDER=openrouter in .env",
            file=sys.stderr,
        )
        return 2

    try:
        encoder = get_encoder(settings)
        llm = get_llm(settings)
    except Exception as exc:
        print(f"could not build OpenRouter clients: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    items = _embedding_items(rows)
    fingerprint = _fingerprint(items)
    cache_path = _cache_path(args.cache, settings.openrouter_embedding_model, encoder.dimension)
    try:
        vectors = _load_or_embed(
            encoder,
            items,
            cache_path=cache_path,
            fingerprint=fingerprint,
            batch_size=settings.openrouter_batch_size,
            refresh=args.refresh_cache,
        )
    except Exception as exc:
        print(f"embedding failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    reports: dict[str, Any] = {}
    for scenario in scenarios:
        print(f"\n=== scenario={scenario} questions={len(questions)} ===", flush=True)
        try:
            pipeline = _pipeline_for(scenario, rows, vectors, encoder, settings, llm, questions)
            eval_pipeline = make_eval_pipeline(pipeline)
            report = run_eval(
                questions,
                pipeline=_with_progress(eval_pipeline, scenario),
                out_path=args.cache / f"report_{scenario}.json",
            )
        except Exception as exc:
            print(f"scenario {scenario} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        reports[scenario] = report.model_dump(mode="json")
        _print_summary(scenario, report)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "models": {
            "llm": settings.openrouter_model,
            "embedding": settings.openrouter_embedding_model,
            "embedding_dimensions": encoder.dimension,
            "prompt_version": PROMPT_VERSION,
        },
        "corpus": {
            "rows": len(rows),
            "fingerprint": fingerprint,
            "metadata_fingerprint": _metadata_fingerprint(rows),
            "path": str(args.corpus),
            "sources": [path.name for path in corpus_paths],
        },
        "questions": len(questions),
        "questions_file": str(args.questions),
        "questions_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
        "limit": args.limit,
        "scenarios": reports,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(_markdown(payload), encoding="utf-8")
    print(f"\nreport={args.out}")
    print(f"summary={args.md}")
    return 0


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return dedupe_corpus_rows(rows)


def _embedding_items(rows: list[dict[str, Any]]) -> list[tuple[tuple[str, int], str]]:
    items: list[tuple[tuple[str, int], str]] = []
    for row in rows:
        pair = (str(row["device_id"]), int(row["norm_version_id"]))
        text = f"{row.get('contexto') or ''}\n{row.get('texto_literal') or ''}".strip()
        items.append((pair, text))
    return items


def _fingerprint(items: list[tuple[tuple[str, int], str]]) -> str:
    digest = hashlib.sha256()
    for (device_id, version), text in items:
        digest.update(f"{device_id}::{version}::{text}\n".encode())
    return digest.hexdigest()


def _metadata_fingerprint(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        fields = [
            str(row.get("device_id")),
            str(row.get("norm_version_id")),
            str(row.get("vigencia_status")),
            str(row.get("vigencia_inicio")),
            str(row.get("vigencia_fim")),
            str(row.get("search_text")),
        ]
        digest.update("::".join(fields).encode("utf-8") + b"\n")
    return digest.hexdigest()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def _cache_path(cache_dir: Path, model: str, dimension: int) -> Path:
    slug = model.replace("/", "_").replace(":", "_")
    return cache_dir / f"{slug}_{dimension}.npz"


def _load_or_embed(
    encoder: Any,
    items: list[tuple[tuple[str, int], str]],
    *,
    cache_path: Path,
    fingerprint: str,
    batch_size: int,
    refresh: bool,
) -> dict[tuple[str, int], list[float]]:
    if cache_path.exists() and not refresh:
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["fingerprint"].item()) == fingerprint:
            keys = [str(key) for key in cached["keys"].tolist()]
            matrix = cached["vectors"]
            print(f"embeddings: cache hit {cache_path} ({len(keys)} vectors)", flush=True)
            return {
                _split_key(key): [float(value) for value in matrix[index]]
                for index, key in enumerate(keys)
            }

    vectors: list[list[float]] = []
    started = time.perf_counter()
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        batch_vectors = encoder.encode_documents([text for _, text in batch])
        if len(batch_vectors) != len(batch):
            raise ValueError(
                f"encoder returned {len(batch_vectors)} vectors for {len(batch)} texts"
            )
        vectors.extend(batch_vectors)
        done = min(start + batch_size, len(items))
        print(f"embeddings: {done}/{len(items)}", flush=True)
    elapsed = time.perf_counter() - started
    print(f"embeddings: {len(items)} vectors in {elapsed:.1f}s", flush=True)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    keys = [f"{device_id}::{version}" for (device_id, version), _ in items]
    np.savez_compressed(
        cache_path,
        vectors=np.asarray(vectors, dtype=np.float32),
        keys=np.asarray(keys),
        fingerprint=np.asarray(fingerprint),
    )
    return {pair: vector for (pair, _), vector in zip(items, vectors, strict=True)}


def _split_key(key: str) -> tuple[str, int]:
    device_id, version = key.rsplit("::", 1)
    return device_id, int(version)


def _pipeline_for(
    scenario: str,
    rows: list[dict[str, Any]],
    vectors: dict[tuple[str, int], list[float]],
    encoder: Any,
    settings: Any,
    llm: Any,
    questions: list[EvalQuestion],
) -> Any:
    if scenario == "gold":
        return GoldContextPipeline(
            repo=InMemoryRepo(rows),
            settings=settings,
            llm=llm,
            gold_by_question={question.pergunta: question.device_ids for question in questions},
        )
    return build_benchmark_pipeline(
        rows=rows,
        vectors=vectors,
        encoder=encoder,
        settings=settings,
        llm=llm,
        mode=scenario,
    )


def _with_progress(pipeline: Any, scenario: str) -> Any:
    def run(question: dict[str, Any]) -> Any:
        started = time.perf_counter()
        result = pipeline(question)
        elapsed = (time.perf_counter() - started) * 1000.0
        print(f"[{scenario}] {question.get('id')} {elapsed:.0f}ms", flush=True)
        return result

    return run


def _print_summary(scenario: str, report: Any) -> None:
    print(
        f"[{scenario}] recall@10={report.recall_at_10:.3f} "
        f"mrr={report.mrr_at_10:.3f} ndcg={report.ndcg_at_10:.3f} "
        f"cit_precision={report.citation_precision:.3f} "
        f"cit_coverage={report.citation_coverage:.3f} "
        f"groundedness={report.groundedness:.3f} "
        f"abstention={report.abstention_accuracy:.3f} "
        f"emergency={report.emergency_routing:.3f} "
        f"p50={report.latency_p50_ms:.0f}ms p95={report.latency_p95_ms:.0f}ms",
        flush=True,
    )
    if report.failures:
        print(f"[{scenario}] failures={', '.join(report.failures)}", flush=True)
    if report.threshold_failures:
        print(f"[{scenario}] thresholds={'; '.join(report.threshold_failures)}", flush=True)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Benchmark OpenRouter",
        "",
        f"- Gerado em: `{payload['generated_at']}`",
        f"- LLM: `{payload['models']['llm']}`",
        f"- Embeddings: `{payload['models']['embedding']}` "
        f"({payload['models']['embedding_dimensions']}d)",
        f"- Corpus: {payload['corpus']['rows']} dispositivos",
        f"- Fingerprint: `{payload['corpus']['fingerprint'][:16]}…`",
        f"- Perguntas: {payload['questions']}",
        f"- Commit: `{payload.get('git_commit') or 'desconhecido'}`",
        f"- Prompt: `{payload['models'].get('prompt_version', 'desconhecido')}`",
        "",
        "| Cenário | Recall@10 | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | "
        "Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, report in payload["scenarios"].items():
        lines.append(
            f"| {name} | {report['recall_at_10']:.3f} | {report['recall_per_question']:.3f} | "
            f"{report['mrr_at_10']:.3f} | {report['ndcg_at_10']:.3f} | "
            f"{report['citation_precision']:.3f} | {report['citation_coverage']:.3f} | "
            f"{report['groundedness']:.3f} | {report['abstention_accuracy']:.3f} | "
            f"{report['emergency_routing']:.3f} | {report['latency_p50_ms']:.0f} | "
            f"{report['latency_p95_ms']:.0f} |"
        )
    lines.extend(["", "## Falhas por cenário", ""])
    for name, report in payload["scenarios"].items():
        failures = report.get("failures") or []
        lines.append(f"- **{name}**: {', '.join(failures) if failures else 'nenhuma'}")
    lines.extend(
        [
            "",
            "## Notas",
            "",
            "- **gold** é contexto-ouro: recall@10, MRR e nDCG são 1,0 por construção; "
            "ele mede geração/citação, não recuperação.",
            "- A latência inclui rede e LLM; no cenário gold, emergência e fora do corpus "
            "não chamam o LLM, por isso o p50 pode ser 0 ms.",
            "- O corpus é local (`data/processed` não versionado), gerado pela ingestão "
            "das fontes oficiais; o fingerprint identifica a execução.",
            "- Harness em memória: BM25 aproximado (não é o FTS português do Postgres) "
            "e vetores em RAM. Não é o caminho de produção.",
            "- `passed` e `threshold_failures` de cada cenário estão no JSON, não na tabela.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
