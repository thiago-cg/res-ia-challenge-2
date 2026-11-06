import os
import uuid
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _connect():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")
    try:
        import psycopg
    except ImportError:  # pragma: no cover - dependency is declared
        pytest.skip("psycopg not installed")
    try:
        return psycopg.connect(url, connect_timeout=3)
    except Exception as exc:
        pytest.skip(f"Postgres not reachable at TEST_DATABASE_URL: {exc}")


@pytest.mark.integration
def test_migration_applies_to_empty_database() -> None:
    from scripts.apply_migrations import apply_migrations

    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.norms')")
        if cur.fetchone()[0] is not None:
            pytest.skip("database is not empty; point TEST_DATABASE_URL at a fresh database")

    apply_migrations(os.environ["TEST_DATABASE_URL"], ROOT / "migrations")

    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.devices_current')")
        assert cur.fetchone()[0] is not None

        cur.execute("SELECT extname FROM pg_extension")
        assert {"vector", "pg_trgm", "unaccent"} <= {row[0] for row in cur.fetchall()}

        cur.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
            (["device_versions_no_overlap", "device_questions_version_fk"],),
        )
        assert {"device_versions_no_overlap", "device_questions_version_fk"} <= {
            row[0] for row in cur.fetchall()
        }

        cur.execute("SELECT to_regclass('public.device_versions_embedding_idx')")
        assert cur.fetchone()[0] is not None


@pytest.mark.integration
def test_overlapping_vigencia_is_rejected() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.device_versions')")
        if cur.fetchone()[0] is None:
            pytest.skip("run the migration before the overlap test")

        suffix = uuid.uuid4().hex[:8]
        norm_id = f"test-{suffix}"
        device_id = f"{norm_id}/art1"

        cur.execute(
            "INSERT INTO norms (id, tipo, numero, ano, fonte_url) VALUES (%s, %s, %s, %s, %s)",
            (norm_id, "lei", "1", 2020, "https://example.test"),
        )
        cur.execute(
            """
            INSERT INTO norm_versions (norm_id, vigencia_inicio, fonte_url, content_hash)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (norm_id, date(2020, 1, 1), "https://example.test", f"hash-{suffix}-1"),
        )
        version_one = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO norm_versions (norm_id, vigencia_inicio, fonte_url, content_hash)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (norm_id, date(2021, 1, 1), "https://example.test", f"hash-{suffix}-2"),
        )
        version_two = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO devices (id, norm_id, artigo_id, tipo, rotulo, caminho, ordem)
            VALUES (%s, %s, %s, 'artigo', 'Art. 1', 'Art. 1', 1)
            """,
            (device_id, norm_id, device_id),
        )

        def insert_version(version_id: int, inicio: date) -> None:
            cur.execute(
                """
                INSERT INTO device_versions (
                    device_id, norm_id, norm_version_id, texto_literal, contexto,
                    citacao, vigencia_status, vigencia_inicio, fonte_url,
                    content_hash, qdrant_point_id, search_text
                ) VALUES (%s, %s, %s, %s, %s, %s, 'vigente', %s, %s, %s, %s, %s)
                """,
                (
                    device_id,
                    norm_id,
                    version_id,
                    "texto",
                    "contexto",
                    "citacao",
                    inicio,
                    "https://example.test",
                    f"hash-{version_id}",
                    uuid.uuid4(),
                    "texto",
                ),
            )

        insert_version(version_one, date(2020, 1, 1))
        with pytest.raises(Exception, match="overlapping"):
            insert_version(version_two, date(2021, 1, 1))
        conn.rollback()
