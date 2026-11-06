from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from src.contracts import Device, DeviceVersion
from src.index.load_db import load_parse_result
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


def _result(norm_id: str) -> ParseResult:
    devices = [
        Device(
            id=f"{norm_id}/art1",
            norm_id=norm_id,
            parent_id=None,
            artigo_id=f"{norm_id}/art1",
            tipo="artigo",
            rotulo="Art. 1",
            caminho="Art. 1",
            ordem=1,
        ),
        Device(
            id=f"{norm_id}/art1/cpt",
            norm_id=norm_id,
            parent_id=f"{norm_id}/art1",
            artigo_id=f"{norm_id}/art1",
            tipo="caput",
            rotulo="caput",
            caminho="Art. 1 > caput",
            ordem=2,
        ),
    ]
    versions = [
        DeviceVersion(
            device_id=device.id,
            norm_version_id=1,
            texto_literal=f"Texto de {device.id}",
            texto_anterior=None,
            contexto="Norma de teste",
            citacao="Norma de teste, art. 1",
            vigencia_status="vigente",
            redacao_dada_por=None,
            vigencia_inicio=date(2020, 1, 1),
            vigencia_fim=None,
            fonte_url="https://example.test",
            content_hash="placeholder",
            qdrant_point_id=uuid5(NAMESPACE_URL, device.id),
            search_text="",
        )
        for device in devices
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
def test_load_parse_result_twice_keeps_row_counts() -> None:
    suffix = uuid.uuid4().hex[:8]
    norm_id = f"b3-load-{suffix}"

    with _connect() as conn:
        _ensure_schema(conn)
        result = _result(norm_id)

        first = load_parse_result(conn, result)
        second = load_parse_result(conn, result)

        assert first.devices_loaded == 2
        assert first.versions_loaded == 2
        assert second.versions_loaded == 0
        assert second.versions_skipped == 2

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM devices WHERE norm_id = %s",
                (norm_id,),
            )
            assert cur.fetchone()[0] == 2
            cur.execute(
                "SELECT count(*) FROM device_versions WHERE norm_id = %s",
                (norm_id,),
            )
            assert cur.fetchone()[0] == 2
            cur.execute(
                "SELECT count(*) FROM device_versions WHERE norm_id = %s AND embedding IS NOT NULL",
                (norm_id,),
            )
            assert cur.fetchone()[0] == 0

        conn.rollback()
