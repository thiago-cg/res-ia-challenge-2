from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import pytest

from src.index.pgvector import dense_search, fts_search, update_embedding

ROOT = Path(__file__).resolve().parents[2]
DIMENSION = 1024
REQUIRED_TABLES = {"norms", "norm_versions", "devices", "device_versions"}


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


def _vector(active: int) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[active] = 1.0
    return vector


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (sorted(REQUIRED_TABLES),),
        )
        present = {row[0] for row in cur.fetchall()}

    missing = REQUIRED_TABLES - present
    if not missing:
        return
    if present:
        pytest.skip(f"pgvector schema incomplete; missing tables: {sorted(missing)}")

    from scripts.apply_migrations import apply_migrations

    conn.rollback()
    apply_migrations(os.environ["TEST_DATABASE_URL"], ROOT / "migrations")


@pytest.mark.integration
def test_dense_and_fts_pick_the_version_that_was_in_force_on_the_fact_date() -> None:
    suffix = uuid.uuid4().hex[:8]
    norm_id = f"idx04-{suffix}"
    device_id = f"{norm_id}/art1"

    with _connect() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO norms (id, tipo, numero, ano, fonte_url) "
                "VALUES (%s, 'lei', '1', 2020, 'https://example.test')",
                (norm_id,),
            )
            cur.execute(
                "INSERT INTO norm_versions (norm_id, vigencia_inicio, fonte_url, content_hash) "
                "VALUES (%s, %s, 'https://example.test', %s) RETURNING id",
                (norm_id, date(2020, 1, 1), f"{suffix}-old"),
            )
            old_norm_version = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO norm_versions (norm_id, vigencia_inicio, fonte_url, content_hash) "
                "VALUES (%s, %s, 'https://example.test', %s) RETURNING id",
                (norm_id, date(2021, 1, 1), f"{suffix}-new"),
            )
            new_norm_version = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO devices (id, norm_id, artigo_id, tipo, rotulo, caminho, ordem) "
                "VALUES (%s, %s, %s, 'artigo', 'Art. 1', 'Art. 1', 1)",
                (device_id, norm_id, device_id),
            )

            def insert_version(
                norm_version_id: int,
                *,
                inicio: date,
                fim: date | None,
                texto: str,
                embedding: list[float],
            ) -> None:
                cur.execute(
                    """
                    INSERT INTO device_versions (
                        device_id, norm_id, norm_version_id, texto_literal, contexto,
                        citacao, vigencia_status, vigencia_inicio, vigencia_fim,
                        fonte_url, content_hash, qdrant_point_id, search_text, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'vigente', %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        device_id,
                        norm_id,
                        norm_version_id,
                        texto,
                        "contexto",
                        f"Lei 1, art. 1 ({texto})",
                        inicio,
                        fim,
                        "https://example.test",
                        f"{suffix}-{norm_version_id}",
                        uuid.uuid4(),
                        texto,
                        _literal(embedding),
                    ),
                )

            insert_version(
                old_norm_version,
                inicio=date(2020, 1, 1),
                fim=date(2020, 12, 31),
                texto="medida protetiva antiga",
                embedding=_vector(0),
            )
            insert_version(
                new_norm_version,
                inicio=date(2021, 1, 1),
                fim=None,
                texto="medida protetiva nova",
                embedding=_vector(1),
            )

        old_hits = [
            hit
            for hit in dense_search(conn, _vector(0), limit=50, data_fato=date(2020, 6, 1))
            if hit.device_id == device_id
        ]
        assert [hit.norm_version_id for hit in old_hits] == [old_norm_version]

        new_hits = [
            hit
            for hit in dense_search(conn, _vector(0), limit=50, data_fato=date(2022, 6, 1))
            if hit.device_id == device_id
        ]
        assert [hit.norm_version_id for hit in new_hits] == [new_norm_version]

        fts_hits = [
            hit
            for hit in fts_search(conn, "medida protetiva", limit=50, data_fato=date(2020, 6, 1))
            if hit.device_id == device_id
        ]
        assert [hit.norm_version_id for hit in fts_hits] == [old_norm_version]

        update_embedding(
            conn,
            device_id,
            new_norm_version,
            _vector(0),
            "harrier-oss-v1-0.6b",
            "rev-test",
            "hash-test",
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding_model, embedding_model_revision, embedding_text_hash "
                "FROM device_versions WHERE device_id = %s AND norm_version_id = %s",
                (device_id, new_norm_version),
            )
            assert cur.fetchone() == ("harrier-oss-v1-0.6b", "rev-test", "hash-test")

        conn.rollback()


@pytest.mark.integration
def test_current_search_and_current_version_exclude_rows_closed_by_diff() -> None:
    from src.api.main import PostgresRepo
    from src.index.load_db import load_current_versions, load_parse_result
    from src.ingest.diff import apply_diff, diff_parse_result
    from tests.integration.test_diff_integration import _result as diff_result

    suffix = uuid.uuid4().hex[:8]
    norm_id = f"fin-current-{suffix}"
    device_id = f"{norm_id}/art1"
    database_url = os.environ["TEST_DATABASE_URL"]

    with _connect() as conn:
        _ensure_schema(conn)
        old = diff_result(norm_id, {device_id: "texto antigo"})
        new = diff_result(norm_id, {device_id: "texto novo"}, start=date(2024, 1, 1))
        load_parse_result(conn, old)
        diff = diff_parse_result(load_current_versions(conn, norm_id), new)
        apply_diff(conn, diff, data_fato=date(2024, 1, 1))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT norm_version_id FROM device_versions "
                "WHERE device_id = %s ORDER BY vigencia_inicio",
                (device_id,),
            )
            old_version, new_version = [row[0] for row in cur.fetchall()]

        update_embedding(conn, device_id, old_version, _vector(0), "test", "rev", "old")
        update_embedding(conn, device_id, new_version, _vector(0), "test", "rev", "new")

        current_hits = [
            hit for hit in dense_search(conn, _vector(0), limit=50) if hit.device_id == device_id
        ]
        assert [hit.norm_version_id for hit in current_hits] == [new_version]

        historical_hits = [
            hit
            for hit in dense_search(conn, _vector(0), limit=50, data_fato=date(2020, 6, 1))
            if hit.device_id == device_id
        ]
        assert [hit.norm_version_id for hit in historical_hits] == [old_version]

        repo = PostgresRepo(database_url)
        assert repo.get_current_version_id(device_id) == new_version
        assert repo.get_current_version_id(device_id, date(2020, 6, 1)) == old_version

        conn.rollback()


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"
