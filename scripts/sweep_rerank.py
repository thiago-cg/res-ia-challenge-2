"""Reranking sweep: none, LLM listwise, and embedding-cosine.

All three read the same hydrated candidate pool, so the only thing under test is
the ordering applied on top of the fused retrieval result.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._evalutil import aggregate, cosine, score_question  # noqa: E402
from src.api.main import PgFtsSearcher, PostgresRepo  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.eval.run import _is_answerable, load_questions  # noqa: E402
from src.generate.llm import get_llm  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402
from src.index.qdrant import QdrantDenseSearcher  # noqa: E402
from src.retrieve.expand import dedupe_by_artigo  # noqa: E402
from src.retrieve.hybrid import hybrid_search  # noqa: E402
from src.retrieve.hydrate import hydrate  # noqa: E402
from src.retrieve.llm_rerank import LLMReranker  # noqa: E402
from src.retrieve.query import understand_query  # noqa: E402

POOL = 30


def top(devices: list[Any], size: int = 10) -> list[str]:
    return [item.device_id for item in dedupe_by_artigo(devices, max_per_article=3)[:size]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data" / "eval" / "questions_150.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "eval" / "sweep_rerank.json")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={"database_url": args.database_url, "qdrant_url": args.qdrant_url}
    )
    questions = [q for q in load_questions(args.questions) if _is_answerable(q)]
    if args.limit:
        questions = questions[: args.limit]

    encoder = get_encoder(settings)
    dense = QdrantDenseSearcher(args.qdrant_url, encoder)
    fts = PgFtsSearcher(args.database_url)
    repo = PostgresRepo(args.database_url)
    llm = get_llm(settings)
    reranker = LLMReranker(llm, pool=POOL)

    variants = ["none", "llm", "cosine"]
    rows: dict[str, list[dict[str, float]]] = {name: [] for name in variants}

    def one(question: Any) -> dict[str, dict[str, float]]:
        plan = understand_query(question.pergunta, expand=True)
        candidates = hybrid_search(
            plan,
            dense=dense,
            fts=fts,
            path="fallback",
            data_fato=None,
            lexical_weight=settings.hybrid_lexical_weight,
        )
        hydrated = hydrate(list(candidates)[:POOL], repo=repo).devices
        scored: dict[str, dict[str, float]] = {}

        scored["none"] = score_question(top(list(hydrated)), question.device_ids)

        reranked = reranker(plan.consulta_juridica, hydrated, top_k=10)
        scored["llm"] = score_question(top(list(reranked)), question.device_ids)

        query_vector = encoder.encode_query(plan.consulta_juridica)
        if query_vector and isinstance(query_vector[0], list):
            query_vector = query_vector[0]
        texts = [
            ((item.texto_literal or "") + " " + (item.citacao or "")).strip() for item in hydrated
        ]
        vectors = encoder.encode_documents(texts) if texts else []
        pairs = sorted(
            zip(hydrated, vectors, strict=False),
            key=lambda pair: cosine(query_vector, pair[1]),
            reverse=True,
        )
        scored["cosine"] = score_question(top([item for item, _ in pairs]), question.device_ids)
        return scored

    started = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool_exec:
        for scored in pool_exec.map(one, questions):
            for name, metrics in scored.items():
                rows[name].append(metrics)
            done += 1
            if done % 10 == 0 or done == len(questions):
                print(
                    "  "
                    + str(done)
                    + "/"
                    + str(len(questions))
                    + " ("
                    + str(round(time.perf_counter() - started))
                    + "s)",
                    flush=True,
                )

    results = [aggregate(value, name) for name, value in rows.items()]
    results.sort(key=lambda row: row["recall_at_10"], reverse=True)
    header = "reranker        R@10  ArtR@10    MRR   nDCG complete"
    print("\n" + header)
    print("-" * len(header))
    for row in results:
        print(
            "{:<14} {:>6.3f} {:>8.3f} {:>6.3f} {:>6.3f} {:>8.3f}".format(
                row["name"],
                row["recall_at_10"],
                row["article_recall_at_10"],
                row["mrr_at_10"],
                row["ndcg_at_10"],
                row["complete"],
            )
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nwrote " + str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
