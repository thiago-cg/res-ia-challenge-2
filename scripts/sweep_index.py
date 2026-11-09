"""Compare the production dense index against the doc2query index.

Both are queried with the same query vector, so the only difference under test
is the text each document was embedded from.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient  # noqa: E402

from scripts._evalutil import aggregate, score_question, select  # noqa: E402
from src.api.main import PgFtsSearcher  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.eval.run import _is_answerable, load_questions  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402
from src.index.qdrant import query_dense  # noqa: E402
from src.retrieve.query import expand_legal_query  # noqa: E402

LIMIT = 50


def keys(items: list[Any]) -> list[tuple[str, int]]:
    return [(str(item.device_id), int(item.norm_version_id)) for item in items]


VARIANTS = [
    ("dense_current", "dense", "devices_qdrant_dense_current", None),
    ("dense_d2q", "dense", "devices_qdrant_dense_d2q", None),
    ("hybrid_current_cap3", "hybrid", "devices_qdrant_dense_current", 3),
    ("hybrid_current_nocap", "hybrid", "devices_qdrant_dense_current", 50),
    ("hybrid_d2q_cap3", "hybrid", "devices_qdrant_dense_d2q", 3),
    ("hybrid_d2q_nocap", "hybrid", "devices_qdrant_dense_d2q", 50),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data" / "eval" / "questions_150.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "eval" / "sweep_index.json")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={"database_url": args.database_url, "qdrant_url": args.qdrant_url}
    )
    questions = [q for q in load_questions(args.questions) if _is_answerable(q)]
    if args.limit:
        questions = questions[: args.limit]

    encoder = get_encoder(settings)
    fts = PgFtsSearcher(args.database_url)
    client = QdrantClient(url=args.qdrant_url)

    rows: dict[str, list[dict[str, float]]] = {name: [] for name, _, _, _ in VARIANTS}
    started = time.perf_counter()
    for index, question in enumerate(questions, 1):
        query = expand_legal_query(question.pergunta)
        vector = encoder.encode_query(query)
        if vector and isinstance(vector[0], list):
            vector = vector[0]
        dense_by_collection = {
            name: keys(query_dense(client, vector, limit=LIMIT, collection_name=name))
            for name in ("devices_qdrant_dense_current", "devices_qdrant_dense_d2q")
        }
        try:
            fts_hits = keys(list(fts.search(query, LIMIT))[:LIMIT])
        except Exception:
            fts_hits = []

        for name, mode, collection, cap in VARIANTS:
            selected = select(
                dense_by_collection[collection],
                fts_hits,
                weight=0.2,
                cap=cap,
                max_devices=10,
                mode=mode,
            )
            rows[name].append(
                score_question([item.device_id for item in selected], question.device_ids)
            )
        if index % 20 == 0 or index == len(questions):
            print(
                "  "
                + str(index)
                + "/"
                + str(len(questions))
                + " ("
                + str(round(time.perf_counter() - started))
                + "s)",
                flush=True,
            )

    results = [aggregate(value, name) for name, value in rows.items()]
    results.sort(key=lambda row: row["recall_at_10"], reverse=True)
    header = "index variant              R@10  ArtR@10    MRR   nDCG complete"
    print("\n" + header)
    print("-" * len(header))
    for row in results:
        print(
            "{:<26} {:>6.3f} {:>8.3f} {:>6.3f} {:>6.3f} {:>8.3f}".format(
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
