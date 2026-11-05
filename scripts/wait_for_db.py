from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urlsplit


def describe_target(database_url: str) -> str:
    parts = urlsplit(database_url)
    host = parts.hostname or "localhost"
    port = parts.port or 5432
    database = parts.path.lstrip("/") or "?"
    return f"{host}:{port}/{database}"


def wait_for_database(database_url: str, timeout: float, interval: float) -> None:
    import psycopg

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            with psycopg.connect(database_url, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return
        except Exception as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"database not ready after {timeout:.0f}s: {describe_target(database_url)}"
            ) from last_error
        time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for a Postgres database using DATABASE_URL (TCP connect + SELECT 1)."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="maximum seconds to wait (default: 60)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between attempts (default: 1)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="override DATABASE_URL",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    target = describe_target(database_url)
    print(f"waiting up to {args.timeout:.0f}s for {target}")
    try:
        wait_for_database(database_url, args.timeout, args.interval)
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: could not connect to {target}: {exc}", file=sys.stderr)
        return 1

    print(f"database ready: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
