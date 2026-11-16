"""Inspeção de apoio ao T02: mostra tabelas e contagens dos bancos do spike."""

from __future__ import annotations

import sys

import psycopg


def show(dsn: str) -> None:
    print(f"== {dsn} ==")
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1"
            ).fetchall()
            print("tabelas:", ", ".join(r[0] for r in rows) or "(nenhuma)")
            for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                if any(r[0] == table for r in rows):
                    n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    print(f"  {table}: {n} linha(s)")
    except Exception as exc:  # noqa: BLE001
        print("  indisponível:", type(exc).__name__, exc)


if __name__ == "__main__":
    for dsn in sys.argv[1:] or ["postgresql://app:app@localhost:5432/spike_t02"]:
        show(dsn)
