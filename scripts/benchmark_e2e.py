"""End-to-end benchmark: full pipeline, real Postgres FTS + Qdrant, real LLM.

The retrieval sweep measures recall; this script measures what a victim would
actually get: whether the answer is produced, cited and grounded, and whether
the system abstains or routes an emergency when it should.  Scenarios differ
only in the retrieval configuration under test.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.main import (  # noqa: E402
    LegalRAGPipeline,
    PgFtsSearcher,
    PostgresRepo,
)
from src.config import get_settings  # noqa: E402
from src.eval.pipeline import make_eval_pipeline  # noqa: E402
from src.eval.run import load_questions, run_eval  # noqa: E402
from src.generate.llm import get_llm  # noqa: E402
from src.generate.prompt import PROMPT_VERSION  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402
from src.index.qdrant import QdrantDenseSearcher  # noqa: E402

CURRENT = "devices_qdrant_dense_current"
D2Q = "devices_qdrant_dense_d2q"

SCENARIOS: dict[str, dict[str, Any]] = {
    "hybrid": {"collection": CURRENT, "cap": 3, "mode": "hybrid"},
    "dense_only": {"collection": CURRENT, "cap": 3, "mode": "dense"},
    "d2q": {"collection": D2Q, "cap": 3, "mode": "hybrid"},
    "nocap": {"collection": CURRENT, "cap": 50, "mode": "hybrid"},
}


def build_pipeline(
    *,
    settings: Any,
    repo: PostgresRepo,
    encoder: Any,
    llm: Any,
    collection: str,
    mode: str = "hybrid",
) -> LegalRAGPipeline:
    from src.eval.inmemory import EmptyFtsSearcher

    return LegalRAGPipeline(
        repo=repo,
        settings=settings,
        llm=llm,
        dense=QdrantDenseSearcher(settings.qdrant_url, encoder, collection_name=collection),
        fts=EmptyFtsSearcher() if mode == "dense" else PgFtsSearcher(settings.database_url),
        encoder=encoder,
    )


def summarize(name: str, report: Any) -> dict[str, Any]:
    return {
        "scenario": name,
        "n_questions": report.n_questions,
        "recall_at_10": report.recall_at_10,
        "article_recall_at_10": report.article_recall_at_10,
        "mrr_at_10": report.mrr_at_10,
        "ndcg_at_10": report.ndcg_at_10,
        "citation_precision": report.citation_precision,
        "citation_coverage": report.citation_coverage,
        "groundedness": report.groundedness,
        "abstention_accuracy": report.abstention_accuracy,
        "emergency_routing": report.emergency_routing,
        "latency_p50_ms": report.latency_p50_ms,
        "latency_p95_ms": report.latency_p95_ms,
        "passed": report.passed,
        "failures": report.failures,
        "threshold_failures": report.threshold_failures,
        "by_split": {
            split: {
                "recall_at_10": agg.recall_at_10,
                "article_recall_at_10": agg.article_recall_at_10,
                "count": agg.count,
            }
            for split, agg in report.by_split.items()
        },
    }


def _with_progress(pipeline: Any, total: int, started: float) -> Any:
    """Wrap the eval pipeline so a long run reports where it is."""

    counter = {"n": 0}

    def run(question: dict[str, Any]) -> Any:
        counter["n"] += 1
        if counter["n"] % 10 == 0:
            elapsed = time.perf_counter() - started
            print(
                "  " + str(counter["n"]) + "/" + str(total) + " (" + str(round(elapsed)) + "s)",
                flush=True,
            )
        return pipeline(question)

    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data" / "eval" / "questions_150.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "eval" / "benchmark_e2e.json")
    parser.add_argument("--md", type=Path, default=ROOT / "data" / "eval" / "benchmark_e2e.md")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--scenarios", default="hybrid,dense_only,d2q")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={"database_url": args.database_url, "qdrant_url": args.qdrant_url}
    )
    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]

    encoder = get_encoder(settings)
    llm = get_llm(settings)
    repo = PostgresRepo(settings.database_url)

    if not encoder.encode_query("verificacao de disponibilidade"):
        print("encoder returned an empty vector", file=sys.stderr)
        return 2
    llm.complete("Responda apenas OK.", "Diga OK.", timeout=60)

    results: dict[str, Any] = {}
    for name in [item.strip() for item in args.scenarios.split(",") if item.strip()]:
        spec = SCENARIOS.get(name)
        if spec is None:
            print("unknown scenario " + name, file=sys.stderr)
            return 2
        scenario_settings = settings.model_copy(
            update={"max_devices_per_article": int(spec["cap"])}
        )
        pipeline = build_pipeline(
            settings=scenario_settings,
            repo=repo,
            encoder=encoder,
            llm=llm,
            collection=str(spec["collection"]),
            mode=str(spec.get("mode", "hybrid")),
        )
        eval_pipeline = make_eval_pipeline(pipeline)
        print(
            "\n=== "
            + name
            + " (collection="
            + str(spec["collection"])
            + ", cap="
            + str(spec["cap"])
            + ") ===",
            flush=True,
        )
        report = run_eval(
            questions,
            pipeline=_with_progress(eval_pipeline, len(questions), time.perf_counter()),
            out_path=None,
        )
        results[name] = summarize(name, report)
        print(
            f"  recall@10={report.recall_at_10:.3f}"
            f" art={report.article_recall_at_10:.3f}"
            f" cit_cov={report.citation_coverage:.3f}"
            f" grounded={report.groundedness:.3f}"
            f" abst={report.abstention_accuracy or 0.0:.3f}"
            f" emerg={report.emergency_routing or 0.0:.3f}"
            f" p50={report.latency_p50_ms:.0f}ms pass={report.passed}",
            flush=True,
        )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "models": {
            "llm": settings.openrouter_model,
            "provider_only": settings.openrouter_provider_only,
            "embedding": settings.openrouter_embedding_model,
            "embedding_dimensions": encoder.dimension,
            "prompt_version": PROMPT_VERSION,
            "query_expansion": settings.query_expansion,
            "lexical_weight": settings.hybrid_lexical_weight,
        },
        "questions": len(questions),
        "questions_file": str(args.questions),
        "scenarios": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md.write_text(_markdown(payload), encoding="utf-8")
    print("\nwrote " + str(args.out) + " and " + str(args.md))
    return 0


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Benchmark end-to-end",
        "",
        "- Gerado em: " + payload["generated_at"],
        "- Modelo: "
        + payload["models"]["llm"]
        + " (provedor "
        + (payload["models"]["provider_only"] or "padrao")
        + ")",
        "- Embeddings: "
        + payload["models"]["embedding"]
        + " ("
        + str(payload["models"]["embedding_dimensions"])
        + "d)",
        "- Perguntas: " + str(payload["questions"]),
        "",
        "| cenario | recall@10 | artigo@10 | cit. cobertura | groundedness"
        " | abstenção | emergência | p50 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in payload["scenarios"].items():
        lines.append(
            "| "
            + name
            + " | {:.3f}".format(row["recall_at_10"])
            + " | {:.3f}".format(row["article_recall_at_10"])
            + " | {:.3f}".format(row["citation_coverage"])
            + " | {:.3f}".format(row["groundedness"])
            + " | {:.3f}".format(row["abstention_accuracy"] or 0.0)
            + " | {:.3f}".format(row["emergency_routing"] or 0.0)
            + " | {:.0f} ms".format(row["latency_p50_ms"])
            + " |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
