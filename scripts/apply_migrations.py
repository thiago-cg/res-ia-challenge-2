"""Aplica migrations/*.sql em ordem, com controle de versão (D10).

Antes, cada execução reaplicava todos os .sql e falhava em qualquer banco já migrado
("relation norms already exists"). Agora existe a tabela de controle "schema_migrations":
arquivo já aplicado é pulado, e o registro é gravado na mesma transação da execução.

Basear um banco legado (migrado antes da tabela de controle existir):

    python scripts/apply_migrations.py \
        --mark-applied 001_init.sql --mark-applied 002_norms_nullable.sql

Aplicar só um arquivo:

    python scripts/apply_migrations.py --only 003
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTROL_TABLE = "schema_migrations"


def migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(Path(migrations_dir).glob("*.sql"))


def _ensure_control(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CONTROL_TABLE} (
            filename   text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def _applied(cur) -> set[str]:
    cur.execute(f"SELECT filename FROM {CONTROL_TABLE}")
    return {row[0] for row in cur.fetchall()}


def _record(cur, filename: str) -> None:
    cur.execute(
        f"INSERT INTO {CONTROL_TABLE} (filename) VALUES (%s) ON CONFLICT (filename) DO NOTHING",
        (filename,),
    )


def apply_migrations(
    database_url: str,
    migrations_dir: Path | None = None,
    *,
    only: tuple[str, ...] = (),
    mark_applied: tuple[str, ...] = (),
) -> list[Path]:
    """Aplica o que falta e devolve os arquivos efetivamente aplicados."""

    import psycopg

    origem = migrations_dir or ROOT / "migrations"
    files = migration_files(origem)
    if not files:
        raise FileNotFoundError(f"no .sql migrations found in {origem}")

    aplicados: list[Path] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            _ensure_control(cur)
        conn.commit()

        nomes = {p.name for p in files}
        with conn.cursor() as cur:
            conhecidos = _applied(cur)
            for nome in mark_applied:
                if nome not in nomes:
                    raise FileNotFoundError(f"unknown migration to mark: {nome}")
                _record(cur, nome)
                # sem isto o laço abaixo reexecutaria o arquivo acabado de marcar
                conhecidos.add(nome)
            conn.commit()

        for path in files:
            if path.name in conhecidos:
                continue
            if only and not any(path.name.startswith(token) for token in only):
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                _record(cur, path.name)
            conn.commit()
            print(f"applied {path.name}")
            aplicados.append(path)
    return aplicados


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply pending migrations/*.sql in order using DATABASE_URL."
    )
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=None,
        help="directory with .sql files (default: ./migrations)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="TOKEN",
        help="apply only files whose name starts with TOKEN (repeatable)",
    )
    parser.add_argument(
        "--mark-applied",
        action="append",
        default=[],
        metavar="FILE",
        help="record FILE as applied without executing it (baseline of a legacy database)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    try:
        aplicados = apply_migrations(
            database_url,
            args.migrations_dir,
            only=tuple(args.only),
            mark_applied=tuple(args.mark_applied),
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # psycopg.Error: nomear o tipo evita "error: " vazio
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not aplicados:
        print("done: nothing to apply")
        return 0
    print(f"done: {len(aplicados)} migration(s) applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
