"""Diff a new parse result against loaded rows and reindex only changes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from src.contracts import Device, DeviceVersion
from src.index.load_db import (
    _ensure_norm_version,
    _insert_device_version,
    _upsert_device,
)
from src.ingest.models import ParseResult


class DiffReport(BaseModel):
    norm_id: str
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    new_versions: dict[str, DeviceVersion] = Field(default_factory=dict)
    new_devices: dict[str, Device] = Field(default_factory=dict)
    old_rows: dict[str, Any] = Field(default_factory=dict)


class ReindexReport(BaseModel):
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    reindexed: list[str] = Field(default_factory=list)
    closed: list[str] = Field(default_factory=list)


def _read_row(row: object) -> tuple[str, str | None, str | None]:
    if isinstance(row, DeviceVersion):
        return row.device_id, row.content_hash, None
    if isinstance(row, Mapping):
        device_id = row.get("device_id") or row.get("id")
        if not device_id:
            raise ValueError("old row is missing device_id")
        content_hash = row.get("content_hash") or row.get("hash")
        norm_id = row.get("norm_id")
        return str(device_id), _optional(content_hash), _optional(norm_id)
    device_id = getattr(row, "device_id", None)
    if device_id is None:
        raise ValueError(f"unsupported old row: {row!r}")
    return (
        str(device_id),
        _optional(getattr(row, "content_hash", None)),
        _optional(getattr(row, "norm_id", None)),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


def diff_parse_result(
    old_rows: Sequence[object],
    new_result: ParseResult,
) -> DiffReport:
    """Classify devices as added, changed, removed or unchanged."""
    old: dict[str, object] = {}
    old_hashes: dict[str, str | None] = {}
    for row in old_rows:
        device_id, content_hash, norm_id = _read_row(row)
        if norm_id is not None and norm_id != new_result.norm.id:
            raise ValueError(f"norm mismatch for {device_id}: {norm_id} != {new_result.norm.id}")
        old[device_id] = row
        old_hashes[device_id] = content_hash

    new_versions = {version.device_id: version for version in new_result.versions}
    old_ids = set(old)
    new_ids = set(new_versions)

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    common = sorted(old_ids & new_ids)
    changed = [
        device_id
        for device_id in common
        if old_hashes[device_id] != new_versions[device_id].content_hash
    ]
    unchanged = [device_id for device_id in common if device_id not in set(changed)]

    return DiffReport(
        norm_id=new_result.norm.id,
        added=added,
        changed=changed,
        removed=removed,
        unchanged=unchanged,
        new_versions={device_id: new_versions[device_id] for device_id in added + changed},
        new_devices={device.id: device for device in new_result.devices},
        old_rows={device_id: old[device_id] for device_id in removed + changed},
    )


def _close_previous(conn: Any, device_id: str, new_start: date) -> None:
    end = new_start - timedelta(days=1)
    sql = """
        UPDATE device_versions
        SET vigencia_fim = %s
        WHERE device_id = %s
          AND vigencia_fim IS NULL
          AND vigencia_inicio <= %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (end, device_id, end))


def _close_removed(conn: Any, device_id: str, end: date) -> None:
    sql = """
        UPDATE device_versions
        SET vigencia_fim = %s, vigencia_status = 'revogado'
        WHERE device_id = %s
          AND vigencia_fim IS NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql, (end, device_id))


def apply_diff(
    conn: Any,
    diff: DiffReport,
    *,
    data_fato: date | None = None,
) -> ReindexReport:
    """Create/close versions for the diff and report what must be reindexed."""
    report = ReindexReport(
        added=list(diff.added),
        changed=list(diff.changed),
        removed=list(diff.removed),
        unchanged=list(diff.unchanged),
    )

    for device_id in diff.added + diff.changed:
        version = diff.new_versions[device_id]
        device = diff.new_devices.get(device_id)
        if device is not None:
            _upsert_device(conn, device)

        start = data_fato or version.vigencia_inicio
        if device_id in diff.changed:
            _close_previous(conn, device_id, start)
            report.closed.append(device_id)

        event_id = _ensure_norm_version(
            conn,
            diff.norm_id,
            start,
            version.fonte_url,
            version.content_hash,
        )
        effective = version.model_copy(update={"vigencia_inicio": start})
        _insert_device_version(conn, diff.norm_id, effective, event_id)
        report.reindexed.append(device_id)

    end = data_fato or date.today()
    for device_id in diff.removed:
        _close_removed(conn, device_id, end)
        report.closed.append(device_id)

    return report
