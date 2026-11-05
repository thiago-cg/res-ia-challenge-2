from __future__ import annotations

from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from src.contracts import Device, DeviceVersion
from src.ingest.diff import apply_diff, diff_parse_result
from src.ingest.models import Norm, ParseResult
from src.ingest.normalize import normalize_parse_result
from tests.unit.db_fakes import FakeConnection


def _device(device_id: str) -> Device:
    return Device(
        id=device_id,
        norm_id="lmp",
        parent_id=None,
        artigo_id=device_id,
        tipo="artigo",
        rotulo=device_id,
        caminho=device_id,
        ordem=1,
    )


def _version(device_id: str, literal: str = "Texto vigente.") -> DeviceVersion:
    return DeviceVersion(
        device_id=device_id,
        norm_version_id=1,
        texto_literal=literal,
        texto_anterior=None,
        contexto="Lei nº 11.340/2006",
        citacao="Lei nº 11.340/2006, art. 1º",
        vigencia_status="vigente",
        redacao_dada_por=None,
        vigencia_inicio=date(2020, 1, 1),
        vigencia_fim=None,
        fonte_url="https://example.test",
        content_hash="placeholder",
        qdrant_point_id=uuid5(NAMESPACE_URL, device_id),
        search_text="",
    )


def _result(*device_ids: str, literals: dict[str, str] | None = None) -> ParseResult:
    literals = literals or {}
    devices = [_device(device_id) for device_id in device_ids]
    versions = [
        _version(device_id, literals.get(device_id, "Texto vigente.")) for device_id in device_ids
    ]
    return normalize_parse_result(
        ParseResult(
            norm=Norm(id="lmp", tipo="lei", numero="11.340", ano=2006),
            devices=devices,
            versions=versions,
        )
    )


def _old_rows(*rows: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {"device_id": device_id, "content_hash": content_hash} for device_id, content_hash in rows
    ]


def test_diff_classifies_added_changed_removed_and_unchanged() -> None:
    new = _result("lmp/art1", "lmp/art2", "lmp/art3", literals={"lmp/art2": "Texto novo."})
    hashes = {version.device_id: version.content_hash for version in new.versions}

    diff = diff_parse_result(
        _old_rows(
            ("lmp/art1", hashes["lmp/art1"]),
            ("lmp/art2", "old-hash"),
            ("lmp/art9", "removed-hash"),
        ),
        new,
    )

    assert diff.added == ["lmp/art3"]
    assert diff.changed == ["lmp/art2"]
    assert diff.removed == ["lmp/art9"]
    assert diff.unchanged == ["lmp/art1"]


def test_apply_diff_changed_creates_one_new_version_and_closes_old() -> None:
    conn = FakeConnection()
    new = _result("lmp/art1", literals={"lmp/art1": "Texto novo."})
    diff = diff_parse_result(_old_rows(("lmp/art1", "old-hash")), new)

    report = apply_diff(conn, diff, data_fato=date(2024, 1, 1))

    assert report.reindexed == ["lmp/art1"]
    assert report.closed == ["lmp/art1"]
    inserts = [sql for sql, _ in conn.executions if sql.startswith("INSERT INTO device_versions")]
    closes = [
        (sql, params)
        for sql, params in conn.updates
        if sql.startswith("UPDATE device_versions") and "revogado" not in sql
    ]
    assert len(inserts) == 1
    assert len(closes) == 1
    assert closes[0][1][0] == date(2023, 12, 31)
    assert any(
        date(2024, 1, 1) in params for sql, params in conn.executions if "device_versions" in sql
    )


def test_apply_diff_unchanged_creates_nothing() -> None:
    conn = FakeConnection()
    new = _result("lmp/art1")
    hashes = {version.device_id: version.content_hash for version in new.versions}
    diff = diff_parse_result(_old_rows(("lmp/art1", hashes["lmp/art1"])), new)

    report = apply_diff(conn, diff, data_fato=date(2024, 1, 1))

    assert report.reindexed == []
    assert report.closed == []
    assert not any("device_versions" in sql for sql, _ in conn.executions)


def test_apply_diff_two_changes_create_two_versions() -> None:
    conn = FakeConnection()
    new = _result(
        "lmp/art1",
        "lmp/art2",
        literals={"lmp/art1": "Novo 1.", "lmp/art2": "Novo 2."},
    )
    diff = diff_parse_result(
        _old_rows(("lmp/art1", "old-1"), ("lmp/art2", "old-2")),
        new,
    )

    report = apply_diff(conn, diff, data_fato=date(2024, 1, 1))

    inserts = [sql for sql, _ in conn.executions if sql.startswith("INSERT INTO device_versions")]
    closes = [
        params
        for sql, params in conn.updates
        if sql.startswith("UPDATE device_versions") and "revogado" not in sql
    ]
    assert sorted(report.reindexed) == ["lmp/art1", "lmp/art2"]
    assert len(inserts) == 2
    assert len(closes) == 2


def test_apply_diff_removed_closes_with_revoked_status() -> None:
    conn = FakeConnection()
    new = _result()
    diff = diff_parse_result(_old_rows(("lmp/art9", "old-hash")), new)

    report = apply_diff(conn, diff, data_fato=date(2024, 1, 1))

    assert report.closed == ["lmp/art9"]
    assert report.reindexed == []
    revoked = [
        (sql, params)
        for sql, params in conn.updates
        if sql.startswith("UPDATE device_versions") and "revogado" in sql
    ]
    assert len(revoked) == 1
    assert revoked[0][1] == (date(2024, 1, 1), "lmp/art9")
    assert not any(sql.startswith("INSERT INTO device_versions") for sql, _ in conn.executions)


def test_apply_diff_added_is_indexed_without_closing_anything() -> None:
    conn = FakeConnection()
    new = _result("lmp/art1")
    diff = diff_parse_result([], new)

    report = apply_diff(conn, diff, data_fato=date(2024, 1, 1))

    assert report.reindexed == ["lmp/art1"]
    assert report.closed == []
    assert any(sql.startswith("INSERT INTO device_versions") for sql, _ in conn.executions)


def test_diff_rejects_a_norm_mismatch_between_old_and_new_rows() -> None:
    new = _result("lmp/art1")
    old = [{"device_id": "lmp/art1", "content_hash": "x", "norm_id": "other"}]

    with pytest.raises(ValueError, match="norm"):
        diff_parse_result(old, new)
