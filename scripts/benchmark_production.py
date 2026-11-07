"""Production-shaped benchmark: Postgres FTS + Qdrant dense + real hydration.

Unlike ``scripts/benchmark_openrouter.py``, this script does not simulate
anything: lexical search runs on Postgres ``tsvector``/``websearch_to_tsquery``,
dense search runs on a real Qdrant collection, and text/citation hydration comes
from ``device_versions`` by ``(device_id, norm_version_id)``.

Scenarios:
- ``dense``: Qdrant dense only (no lexical list);
- ``hybrid``: Postgres FTS + Qdrant dense fused with RRF (production shape);
- ``gold``: gold devices hydrated from Postgres, isolating generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.api.main import LegalRAGPipeline, PostgresRepo, build_default_pipeline
from src.config import Settings, get_settings
from src.eval.inmemory import EmptyFtsSearcher, GoldContextPipeline
from src.eval.pipeline import make_eval_pipeline
from src.eval.run import EvalQuestion, load_questions, run_eval
from src.generate.llm import get_llm
from src.generate.prompt import PROMPT_VERSION
from src.index.embed import get_encoder
from src.index.qdrant import QdrantDenseSearcher

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = PROJECT_ROOT / "data" / "eval" / "questions.jsonl"
DEFAULT_OUT = PROJECT_ROOT / "data" / "eval" / "benchmark_production.json"
DEFAULT_MD = PROJECT_ROOT / "data" / "eval" / "benchmark_production.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument(
        "--scenarios",
        default="dense,hybrid,gold",
        help="comma-separated: dense,hybrid,gold",
    )
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

    settings = get_settings().model_copy(
        update={
            "database_url": args.database_url,
            "qdrant_url": args.qdrant_url,
            "retrieval_path": "fallback",
            "dense_backend": "qdrant",
        }
    )
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
        repo = PostgresRepo(settings.database_url)
        repo.health_snapshot()
    except Exception as exc:
        print(
            f"could not build Postgres/OpenRouter clients: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    reports: dict[str, Any] = {}
    qdrant_collection: str | None = None
    for scenario in scenarios:
        print(f"\n=== scenario={scenario} questions={len(questions)} ===", flush=True)
        try:
            pipeline = _pipeline_for(
                scenario,
                settings=settings,
                repo=repo,
                encoder=encoder,
                llm=llm,
                questions=questions,
            )
            if scenario in {"dense", "hybrid"}:
                qdrant_collection = getattr(
                    getattr(pipeline, "dense", None), "collection_name", None
                )
            eval_pipeline = make_eval_pipeline(pipeline)
            report = run_eval(
                questions,
                pipeline=_with_progress(eval_pipeline, scenario),
                out_path=args.out.parent / f"report_production_{scenario}.json",
            )
        except Exception as exc:
            print(f"scenario {scenario} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        reports[scenario] = report.model_dump(mode="json")
        _print_summary(scenario, report)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "backend": "postgres-fts+qdrant-dense",
        "models": {
            "llm": settings.openrouter_model,
            "embedding": settings.openrouter_embedding_model,
            "embedding_dimensions": encoder.dimension,
            "prompt_version": PROMPT_VERSION,
            "query_instruction": settings.openrouter_query_instruction,
        },
        "database": {
            "device_versions": _db_count(repo, "device_versions"),
            "devices": _db_count(repo, "devices"),
        },
        "qdrant": {"collection": qdrant_collection},
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


def _pipeline_for(
    scenario: str,
    *,
    settings: Settings,
    repo: PostgresRepo,
    encoder: Any,
    llm: Any,
    questions: list[EvalQuestion],
) -> Any:
    if scenario == "gold":
        return GoldContextPipeline(
            repo=repo,
            settings=settings,
            llm=llm,
            gold_by_question={question.pergunta: question.device_ids for question in questions},
        )
    if scenario == "dense":
        return LegalRAGPipeline(
            repo=repo,
            settings=settings,
            llm=llm,
            dense=QdrantDenseSearcher(settings.qdrant_url, encoder),
            fts=EmptyFtsSearcher(),
            encoder=encoder,
        )
    if scenario == "hybrid":
        return build_default_pipeline(settings, None)
    raise ValueError(f"unknown scenario: {scenario!r}")


def _with_progress(pipeline: Any, scenario: str) -> Any:
    def run(question: dict[str, Any]) -> Any:
        result = pipeline(question)
        print(f"[{scenario}] {question.get('id')}", flush=True)
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


def _db_count(repo: PostgresRepo, table: str) -> int:
    import psycopg

    with psycopg.connect(repo.database_url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        row = cur.fetchone()
    return int(row[0]) if row else 0


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
    return result.stdout.strip() or None


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Benchmark produÃ§Ã£o: Postgres FTS + Qdrant dense",
        "",
        f"- Gerado em: `{payload['generated_at']}`",
        f"- Backend: `{payload['backend']}`",
        f"- LLM: `{payload['models']['llm']}`",
        f"- Embeddings: `{payload['models']['embedding']}` "
        f"({payload['models']['embedding_dimensions']}d)",
        f"- InstruÃ§Ã£o de consulta: `{payload['models']['query_instruction'] or '(vazia)'}`",
        f"- Postgres: {payload['database']['device_versions']} versÃµes, "
        f"{payload['database']['devices']} dispositivos",
        f"- Qdrant: `{payload['qdrant']['collection']}`",
        f"- Perguntas: {payload['questions']}",
        f"- Commit: `{payload.get('git_commit') or 'desconhecido'}`",
        "",
        "| CenÃ¡rio | Recall@10 | Recall/pergunta | MRR@10 | nDCG@10 | PrecisÃ£o citaÃ§Ã£o | "
        "Cobertura citaÃ§Ã£o | Groundedness | AbstenÃ§Ã£o | EmergÃªncia | p50 (ms) | p95 (ms) |",
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
    lines.extend(["", "## Falhas por cenÃ¡rio", ""])
    for name, report in payload["scenarios"].items():
        failures = report.get("failures") or []
        lines.append(f"- **{name}**: {', '.join(failures) if failures else 'nenhuma'}")
    lines.extend(
        [
            "",
            "## Notas",
            "",
            "- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')`, "
            "`ts_rank_cd`) + Qdrant dense 4096d, fundidos por RRF.",
            "- `dense` usa somente Qdrant; `gold` entrega os dispositivos-ouro "
            "hidratados do Postgres e mede geraÃ§Ã£o/citaÃ§Ã£o, nÃ£o recuperaÃ§Ã£o.",
            "- O Qdrant usa HNSW aproximado; a latÃªncia inclui rede, Postgres, Qdrant e LLM.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
