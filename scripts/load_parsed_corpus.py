"""Load parsed JSONL corpora into Postgres for the real FTS/Qdrant benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.ingest.replay import load_jsonl_corpus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "processed"
DEFAULT_SEED = PROJECT_ROOT / "data" / "seed" / "stj-sumulas.jsonl"
DEFAULT_SOURCES = "lmp,cp,cpp,cnj-rc-5-2020"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--sources", default=DEFAULT_SOURCES)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--keep-invalid-parents", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_ids = [item.strip() for item in args.sources.split(",") if item.strip()]
    paths = [args.corpus / f"{source_id}.jsonl" for source_id in source_ids]
    if args.seed.exists():
        paths.append(args.seed)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        print(f"missing corpus file(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    import psycopg

    try:
        with psycopg.connect(args.database_url) as conn:
            reports = load_jsonl_corpus(
                conn,
                paths,
                drop_invalid_parents=not args.keep_invalid_parents,
            )
            conn.commit()
    except Exception as exc:
        print(f"load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for report in reports:
        print(
            f"{report.norm_id}: devices={report.devices_loaded} "
            f"versions={report.versions_loaded} skipped={report.versions_skipped} "
            f"norm_versions={len(report.norm_version_ids)}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
