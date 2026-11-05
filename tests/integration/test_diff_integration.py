from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from src.contracts import Device, DeviceVersion
from src.index.load_db import load_parse_result
from src.ingest.diff import apply_diff, diff_parse_result
from src.ingest.models import Norm, ParseResult
from src.ingest.normalize import normalize_parse_result

ROOT = Path(__file__).resolve().parents[2]
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


def _result(norm_id: str, literals: dict[str, str]) -> ParseResult:
    device_ids = sorted(literals)
    devices = [
        Device(
            id=device_id,
            norm_id=norm_id,
            parent_id=None,
            artigo_id=device_id,
            tipo="artigo",
            rotulo=device_id,
            caminho=device_id,
            ordem=index,
        )
        for index, device_id in enumerate(device_ids, start=1)
    ]
    versions = [
        DeviceVersion(
            device_id=device_id,
            norm_version_id=1,
            texto_literal=literals[device_id],
            texto_anterior=None,
            contexto="Norma de teste",
            citacao=f"Norma de teste, art. {index}",
            vigencia_status="vigente",
            redacao_dada_por=None,
            vigencia_inicio=date(2020, 1, 1),
            vigencia_fim=None,
            fonte_url="https://example.test",
            content_hash="placeholder",
            qdrant_point_id=uuid5(NAMESPACE_URL, device_id),
            search_text="",
        )
        for index, device_id in enumerate(device_ids, start=1)
    ]
    return normalize_parse_result(
        ParseResult(
            norm=Norm(
                id=norm_id,
                tipo="lei",
                numero="1",
                ano=2020,
                fonte_url="https://example.test",
            ),
            devices=devices,
            versions=versions,
        )
    )


@pytest.mark.integration
def test_apply_diff_creates_one_version_and_closes_one() -> None:
    suffix = uuid.uuid4().hex[:8]
    norm_id = f"b3-diff-{suffix}"
    changed_id = f"{norm_id}/art1"
    unchanged_id = f"{norm_id}/art2"

    with _connect() as conn:
        _ensure_schema(conn)
        load_parse_result(
            conn,
            _result(norm_id, {changed_id: "Texto antigo.", unchanged_id: "Texto estável."}),
        )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT device_id, content_hash, norm_id, vigencia_inicio "
                "FROM device_versions "
                "WHERE norm_id = %s AND vigencia_fim IS NULL",
                (norm_id,),
            )
            old_rows = cur.fetchall()

        assert all(isinstance(row, tuple) for row in old_rows)
        new = _result(norm_id, {changed_id: "Texto novo.", unchanged_id: "Texto estável."})
        diff = diff_parse_result(old_rows, new)
        assert diff.changed == [changed_id]
        assert diff.unchanged == [unchanged_id]

        report = apply_diff(conn, diff, data_fato=date(2024, 1, 1))

        assert report.reindexed == [changed_id]
        assert report.closed == [changed_id]

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM device_versions WHERE norm_id = %s",
                (norm_id,),
            )
            assert cur.fetchone()[0] == 3

            cur.execute(
                "SELECT vigencia_fim FROM device_versions "
                "WHERE device_id = %s AND texto_literal = %s",
                (changed_id, "Texto antigo."),
            )
            assert cur.fetchone()[0] == date(2023, 12, 31)

            cur.execute(
                "SELECT vigencia_inicio, vigencia_fim FROM device_versions "
                "WHERE device_id = %s AND texto_literal = %s",
                (changed_id, "Texto novo."),
            )
            assert cur.fetchone() == (date(2024, 1, 1), None)

            cur.execute(
                "SELECT count(*) FROM device_versions WHERE device_id = %s",
                (unchanged_id,),
            )
            assert cur.fetchone()[0] == 1

        conn.rollback()
