"""Retrieval-strategy sweep against the real Postgres FTS and Qdrant dense index.

The embedding pass is the only expensive step, so it runs once per question and
every fusion, weighting and selection variant is then evaluated offline from the
same rank lists.  That keeps the comparison honest: only the strategy under test
changes, never the candidate pools.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.main import PgFtsSearcher  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.contracts import RetrievedDevice  # noqa: E402
from src.eval.metrics import (  # noqa: E402
    article_recall_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    recall_per_question,
)
from src.eval.run import _is_answerable, load_questions  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402
from src.index.qdrant import QdrantDenseSearcher  # noqa: E402
from src.retrieve.expand import artigo_id, dedupe_by_artigo  # noqa: E402
from src.retrieve.hybrid import rrf  # noqa: E402
from src.retrieve.query import expand_legal_query  # noqa: E402

PER_SEARCH_LIMIT = 50
DEFAULT_MAX_CANDIDATES = 150


def key(item: Any) -> tuple[str, int]:
    return (str(item.device_id), int(item.norm_version_id))


@dataclass(frozen=True)
class Config:
    name: str
    query: str = "expanded"
    mode: str = "hybrid"
    lexical_weight: float = 0.2
    rrf_k: int = 60
    cap: int | None = 3
    max_devices: int = 10
    #: "grouped" is the production dedupe (regroups the list by article);
    #: "ordered" enforces the same cap while keeping the global score order.
    dedupe: str = "grouped"


def configs() -> list[Config]:
    out: list[Config] = []
    out.append(Config("dense__expanded", mode="dense"))
    out.append(Config("dense__raw", query="raw", mode="dense"))
    out.append(Config("lexical__expanded", mode="fts"))
    out.append(Config("lexical__raw", query="raw", mode="fts"))
    for weight in (0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0):
        out.append(Config(f"hybrid__w{weight:g}__expanded", lexical_weight=weight))
        out.append(Config(f"hybrid__w{weight:g}__raw", query="raw", lexical_weight=weight))
    for rrf_k in (10, 30, 60, 100):
        out.append(Config(f"hybrid__w0.2__k{rrf_k}", rrf_k=rrf_k))
    for cap in (None, 1, 2, 3, 5):
        out.append(Config(f"hybrid__w0.2__cap{cap}", cap=cap))
    for cap in (1, 2, 3, 5):
        out.append(Config(f"hybrid__w0.2__ordered_cap{cap}", cap=cap, dedupe="ordered"))
    out.append(Config("dense__ordered_cap3", mode="dense", cap=3, dedupe="ordered"))
    out.append(Config("dense__no_cap", mode="dense", cap=None))
    for max_devices in (10, 20, 50):
        out.append(Config(f"hybrid__w0.2__top{max_devices}", max_devices=max_devices))
    return out


def build_query_variants(text: str) -> dict[str, str]:
    return {"raw": text.strip(), "expanded": expand_legal_query(text)}


def retrieve_pools(
    questions: list[Any],
    *,
    database_url: str,
    qdrant_url: str,
    limit: int | None,
) -> dict[str, dict[str, Any]]:
    settings = get_settings().model_copy(
        update={"database_url": database_url, "qdrant_url": qdrant_url}
    )
    encoder = get_encoder(settings)
    dense = QdrantDenseSearcher(qdrant_url, encoder)
    fts = PgFtsSearcher(database_url)

    pools: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    for index, question in enumerate(questions, 1):
        if not _is_answerable(question):
            continue
        variants = build_query_variants(question.pergunta)
        entry: dict[str, Any] = {"pergunta": question.pergunta, "gold": list(question.device_ids)}
        for name, query in variants.items():
            dense_hits = list(dense.search(query, PER_SEARCH_LIMIT))[:PER_SEARCH_LIMIT]
            try:
                fts_hits = list(fts.search(query, PER_SEARCH_LIMIT))[:PER_SEARCH_LIMIT]
            except Exception as exc:  # pragma: no cover - diagnostics only
                print(f"  fts failed for {question.id}: {exc}", flush=True)
                fts_hits = []
            entry[name] = {
                "dense": [key(item) for item in dense_hits],
                "fts": [key(item) for item in fts_hits],
            }
        pools[question.id] = entry
        if index % 10 == 0 or index == len(questions):
            elapsed = time.perf_counter() - started
            print(f"  retrieved {index}/{len(questions)} ({elapsed:.0f}s)", flush=True)
    return pools


def _normalize_pools(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Rehydrate the JSON cache: RRF keys must be hashable tuples."""

    pools: dict[str, dict[str, Any]] = {}
    for question_id, entry in raw.items():
        normalized: dict[str, Any] = {"pergunta": entry["pergunta"], "gold": entry["gold"]}
        for variant in ("raw", "expanded"):
            if variant in entry:
                normalized[variant] = {
                    leg: [(str(item[0]), int(item[1])) for item in entry[variant][leg]]
                    for leg in ("dense", "fts")
                }
        pools[str(question_id)] = normalized
    return pools


def ordered_cap(devices: Sequence[RetrievedDevice], cap: int) -> list[RetrievedDevice]:
    """Keep at most cap devices per article while preserving the global order."""

    kept: list[RetrievedDevice] = []
    seen: dict[tuple[str, int], int] = {}
    for item in devices:
        group = (artigo_id(item.device_id), item.norm_version_id)
        if seen.get(group, 0) >= cap:
            continue
        seen[group] = seen.get(group, 0) + 1
        kept.append(item)
    return kept


def fuse(pool: dict[str, Any], config: Config) -> list[tuple[str, int]]:
    dense_keys = pool[config.query]["dense"]
    fts_keys = pool[config.query]["fts"]
    if config.mode == "dense":
        fused = dense_keys
    elif config.mode == "fts":
        fused = fts_keys
    else:
        fused = [
            item
            for item, _ in rrf(
                [dense_keys, fts_keys],
                k=config.rrf_k,
                weights=[1.0, config.lexical_weight],
            )
        ]
    devices = [
        RetrievedDevice(
            device_id=device_id,
            norm_version_id=version,
            score=0.0,
            source="dense" if config.mode == "dense" else "bm25",
            texto_literal="",
            citacao=device_id,
        )
        for device_id, version in fused
    ]
    if config.cap is not None:
        if config.dedupe == "ordered":
            devices = ordered_cap(devices, config.cap)
        else:
            devices = list(dedupe_by_artigo(devices, max_per_article=config.cap))
    return [key(item) for item in devices[: config.max_devices]]


def evaluate(
    pools: dict[str, dict[str, Any]], config: Config, questions: list[Any]
) -> dict[str, Any]:
    by_id = {question.id: question for question in questions}
    rows = []
    for question_id, pool in pools.items():
        question = by_id[question_id]
        selected = fuse(pool, config)
        retrieved = [device_id for device_id, _ in selected]
        expected = list(question.device_ids)
        rows.append(
            {
                "recall_at_10": recall_at_k(retrieved, expected, 10),
                "article_recall_at_10": article_recall_at_k(retrieved, expected, 10),
                "recall_per_question": recall_per_question(retrieved, expected, 10),
                "mrr_at_10": mrr_at_k(retrieved, expected, 10),
                "ndcg_at_10": ndcg_at_k(retrieved, expected, 10),
                "recall_at_50": recall_at_k(retrieved, expected, 50),
                "complete": float(set(expected) <= set(retrieved[:10])),
            }
        )
    count = len(rows) or 1
    return {
        "name": config.name,
        "n": len(rows),
        **{metric: round(sum(row[metric] for row in rows) / count, 4) for metric in rows[0]},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data" / "eval" / "questions_150.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "eval" / "sweep_retrieval.json")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pools-cache", type=Path, default=ROOT / "data" / "eval" / "_pools.json")
    args = parser.parse_args(argv)

    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]

    if args.pools_cache.exists():
        print(f"reusing pools from {args.pools_cache}", flush=True)
        pools = _normalize_pools(json.loads(args.pools_cache.read_text(encoding="utf-8")))
    else:
        pools = retrieve_pools(
            questions,
            database_url=args.database_url,
            qdrant_url=args.qdrant_url,
            limit=args.limit,
        )
        args.pools_cache.parent.mkdir(parents=True, exist_ok=True)
        args.pools_cache.write_text(
            json.dumps(pools, ensure_ascii=False),
            encoding="utf-8",
        )

    results = [evaluate(pools, config, questions) for config in configs()]
    results.sort(key=lambda row: row["recall_at_10"], reverse=True)

    print(f"\nquestions (answerable): {len(pools)}")
    header = (
        f"{'strategy':<30} {'R@10':>6} {'ArtR@10':>8}"
        f" {'MRR':>6} {'nDCG':>6} {'R@50':>6} {'complete':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in results:
        print(
            f"{row['name']:<30} {row['recall_at_10']:>6.3f}"
            f" {row['article_recall_at_10']:>8.3f} {row['mrr_at_10']:>6.3f}"
            f" {row['ndcg_at_10']:>6.3f} {row['recall_at_50']:>6.3f}"
            f" {row['complete']:>8.3f}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
