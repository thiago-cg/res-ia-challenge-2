from __future__ import annotations

from datetime import date
from uuid import NAMESPACE_URL, uuid5

from src.contracts import Device, DeviceVersion
from src.index.load_db import load_parse_result, load_versions, record_ingest_run
from src.ingest.models import Norm, ParseResult
from src.ingest.normalize import normalize_parse_result
from tests.unit.db_fakes import FakeConnection


def _result() -> ParseResult:
    devices = [
        Device(
            id="lmp/art1",
            norm_id="lmp",
            parent_id=None,
            artigo_id="lmp/art1",
            tipo="artigo",
            rotulo="Art. 1",
            caminho="Art. 1",
            ordem=1,
        ),
        Device(
            id="lmp/art1/cpt",
            norm_id="lmp",
            parent_id="lmp/art1",
            artigo_id="lmp/art1",
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
            contexto="Lei nº 11.340/2006",
            citacao="Lei nº 11.340/2006, art. 1º",
            vigencia_status="vigente",
            redacao_dada_por=None,
            vigencia_inicio=date(2006, 9, 22),
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
            norm=Norm(id="lmp", tipo="lei", numero="11.340", ano=2006),
            devices=devices,
            versions=versions,
        )
    )


def test_load_parse_result_upserts_all_tables() -> None:
    conn = FakeConnection()
    result = _result()

    report = load_parse_result(conn, result)

    assert report.norm_id == "lmp"
    assert report.norm_version_ids == {"2006-09-22": 1}
    assert report.devices_loaded == 2
    assert report.versions_loaded == 2
    assert report.versions_skipped == 0
    assert conn.norms == {"lmp"}
    assert conn.devices == {"lmp/art1", "lmp/art1/cpt"}
    assert len(conn.norm_versions) == 1
    assert len(conn.device_versions) == 2


def test_load_parse_result_is_idempotent_and_never_overwrites_versions() -> None:
    conn = FakeConnection()
    result = _result()

    load_parse_result(conn, result)
    second = load_parse_result(conn, result)

    assert second.versions_loaded == 0
    assert second.versions_skipped == 2
    assert len(conn.device_versions) == 2

    insert_sql = [
        sql for sql, _ in conn.executions if sql.startswith("INSERT INTO device_versions")
    ]
    assert insert_sql
    assert all("ON CONFLICT (device_id, norm_version_id) DO NOTHING" in sql for sql in insert_sql)
    assert not any(sql.startswith("UPDATE device_versions") for sql, _ in conn.executions)


def test_device_versions_insert_does_not_touch_embedding_columns() -> None:
    conn = FakeConnection()
    load_parse_result(conn, _result())

    insert_sql = next(
        sql for sql, _ in conn.executions if sql.startswith("INSERT INTO device_versions")
    )
    assert "embedding" not in insert_sql


def test_norm_version_is_keyed_by_vigencia_inicio() -> None:
    conn = FakeConnection()
    result = _result()
    result.versions[1] = result.versions[1].model_copy(update={"vigencia_inicio": date(2023, 1, 1)})

    report = load_parse_result(conn, result)

    assert report.norm_version_ids == {"2006-09-22": 1, "2023-01-01": 2}
    assert len(conn.norm_versions) == 2


def test_load_versions_compatibility_wrapper() -> None:
    conn = FakeConnection()

    report = load_versions(conn, _result().versions)

    assert report.norm_id == "lmp"
    assert report.versions_loaded == 2
    assert len(conn.device_versions) == 2


def test_record_ingest_run_inserts_and_updates() -> None:
    conn = FakeConnection()

    run_id = record_ingest_run(conn, "lmp", "running")
    assert conn.ingest_runs == [run_id]

    updated = record_ingest_run(
        conn,
        "lmp",
        "ok",
        ingest_run_id=run_id,
        devices_seen=10,
        devices_changed=2,
    )
    assert updated == run_id
    assert any(sql.startswith("UPDATE ingest_runs") for sql, _ in conn.executions)
