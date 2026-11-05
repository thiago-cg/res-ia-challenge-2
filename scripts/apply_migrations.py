from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(Path(migrations_dir).glob("*.sql"))


def apply_migrations(database_url: str, migrations_dir: Path | None = None) -> list[Path]:
    import psycopg

    files = migration_files(migrations_dir or ROOT / "migrations")
    if not files:
        raise FileNotFoundError(f"no .sql migrations found in {migrations_dir}")

    with psycopg.connect(database_url) as conn:
        for path in files:
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            print(f"applied {path.name}")
    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply every migrations/*.sql in order using DATABASE_URL."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="override DATABASE_URL",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=None,
        help="directory with .sql files (default: ./migrations)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    try:
        files = apply_migrations(database_url, args.migrations_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"done: {len(files)} migration(s) applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
