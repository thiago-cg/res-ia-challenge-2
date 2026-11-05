"""Diff a new parse result against loaded rows and reindex only changes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from src.contracts import Device, DeviceVersion
from src.index.load_db import (
    _ensure_norm_version,
    _insert_device_version,
    _upsert_device,
    source_content_hash,
)
from src.ingest.models import ParseResult
from src.ingest.normalize import normalize_parse_result


class DiffError(Exception):
    """A diff cannot be applied without breaking version history."""


@dataclass(frozen=True)
class OldRow:
    """A loaded ``device_versions`` row normalized for diffing.

    The tuple adapter accepts ``(device_id, content_hash)``,
    ``(device_id, content_hash, norm_id)`` or
    ``(device_id, content_hash, norm_id, vigencia_inicio)``. That is the order
    used by the integration queries and by psycopg's default tuples.
    """

    device_id: str
    content_hash: str | None
    norm_id: str | None = None
    vigencia_inicio: date | None = None


class DiffReport(BaseModel):
    norm_id: str
    source_content_hash: str = ""
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    new_versions: dict[str, DeviceVersion] = Field(default_factory=dict)
    new_devices: dict[str, Device] = Field(default_factory=dict)
    old_rows: dict[str, OldRow] = Field(default_factory=dict)


class ReindexReport(BaseModel):
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    reindexed: list[str] = Field(default_factory=list)
    closed: list[str] = Field(default_factory=list)


def _read_row(row: object) -> OldRow:
    if isinstance(row, DeviceVersion):
        return OldRow(row.device_id, row.content_hash, None, row.vigencia_inicio)
    if isinstance(row, Mapping):
        device_id = row.get("device_id") or row.get("id")
        if not device_id:
            raise ValueError("old row is missing device_id")
        content_hash = row.get("content_hash") or row.get("hash")
        return OldRow(
            device_id=str(device_id),
            content_hash=_optional(content_hash),
            norm_id=_optional(row.get("norm_id")),
            vigencia_inicio=_optional_date(row.get("vigencia_inicio")),
        )
    if isinstance(row, (tuple, list)):
        if len(row) < 2 or len(row) > 4:
            raise ValueError(
                "old row tuple must be (device_id, content_hash[, norm_id[, vigencia_inicio]])"
            )
        values = list(row) + [None] * (4 - len(row))
        if values[0] is None:
            raise ValueError("old row tuple is missing device_id")
        return OldRow(
            device_id=str(values[0]),
            content_hash=_optional(values[1]),
            norm_id=_optional(values[2]),
            vigencia_inicio=_optional_date(values[3]),
        )
    device_id = getattr(row, "device_id", None)
    if device_id is None:
        raise ValueError(f"unsupported old row: {row!r}")
    return OldRow(
        device_id=str(device_id),
        content_hash=_optional(getattr(row, "content_hash", None)),
        norm_id=_optional(getattr(row, "norm_id", None)),
        vigencia_inicio=_optional_date(getattr(row, "vigencia_inicio", None)),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def diff_parse_result(
    old_rows: Sequence[object],
    new_result: ParseResult,
) -> DiffReport:
    """Classify devices as added, changed, removed or unchanged."""
    normalized = normalize_parse_result(new_result)
    old: dict[str, OldRow] = {}
    for row in old_rows:
        parsed = _read_row(row)
        if parsed.norm_id is not None and parsed.norm_id != normalized.norm.id:
            raise ValueError(
                f"norm mismatch for {parsed.device_id}: {parsed.norm_id} != {normalized.norm.id}"
            )
        old[parsed.device_id] = parsed

    new_versions = {version.device_id: version for version in normalized.versions}
    old_ids = set(old)
    new_ids = set(new_versions)

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    common = sorted(old_ids & new_ids)
    changed = [
        device_id
        for device_id in common
        if old[device_id].content_hash != new_versions[device_id].content_hash
    ]
    unchanged = [device_id for device_id in common if device_id not in set(changed)]

    return DiffReport(
        norm_id=normalized.norm.id,
        source_content_hash=source_content_hash(normalized.norm, normalized.versions),
        added=added,
        changed=changed,
        removed=removed,
        unchanged=unchanged,
        new_versions={device_id: new_versions[device_id] for device_id in added + changed},
        new_devices={device.id: device for device in normalized.devices},
        old_rows={device_id: old[device_id] for device_id in removed + changed},
    )


def _close_previous(conn: Any, device_id: str, new_start: date, old_start: date) -> None:
    end = new_start - timedelta(days=1)
    sql = """
        UPDATE device_versions
        SET vigencia_fim = %s
        WHERE device_id = %s
          AND vigencia_fim IS NULL
          AND vigencia_inicio = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (end, device_id, old_start))
        if cur.rowcount == 0:
            raise DiffError(f"{device_id}: no open version starting at {old_start} to close")


def _close_removed(conn: Any, device_id: str, end: date) -> None:
    sql = """
        UPDATE device_versions
        SET vigencia_fim = %s, vigencia_status = 'revogado'
        WHERE device_id = %s
          AND vigencia_fim IS NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql, (end, device_id))


def _check_start(device_id: str, start: date, today: date) -> None:
    if start > today:
        raise DiffError(f"{device_id}: new vigencia_inicio {start} is in the future")


def apply_diff(
    conn: Any,
    diff: DiffReport,
    *,
    data_fato: date | None = None,
    removed_at: date | None = None,
    today: date | None = None,
) -> ReindexReport:
    """Create/close versions for the diff and report what must be reindexed."""
    report = ReindexReport(
        added=list(diff.added),
        changed=list(diff.changed),
        removed=list(diff.removed),
        unchanged=list(diff.unchanged),
    )
    current_day = today or date.today()
    starts: dict[str, date] = {}

    for device_id in diff.added + diff.changed:
        version = diff.new_versions[device_id]
        start = data_fato or version.vigencia_inicio
        _check_start(device_id, start, current_day)
        if device_id in diff.changed:
            old = diff.old_rows.get(device_id)
            old_start = old.vigencia_inicio if old is not None else None
            if old_start is None:
                raise DiffError(
                    f"{device_id}: cannot close the open version without its vigencia_inicio"
                )
            if start <= old_start:
                raise DiffError(
                    f"{device_id}: new vigencia_inicio {start} must be after "
                    f"the current version start {old_start}"
                )
        starts[device_id] = start

    if diff.removed and data_fato is None and removed_at is None:
        raise DiffError("removed devices require data_fato or removed_at to set vigencia_fim")
    removed_end = data_fato or removed_at

    for device_id in diff.added + diff.changed:
        version = diff.new_versions[device_id]
        device = diff.new_devices.get(device_id)
        if device is not None:
            _upsert_device(conn, device)

        start = starts[device_id]
        if device_id in diff.changed:
            old = diff.old_rows[device_id]
            assert old.vigencia_inicio is not None
            _close_previous(conn, device_id, start, old.vigencia_inicio)
            report.closed.append(device_id)

        event_id = _ensure_norm_version(
            conn,
            diff.norm_id,
            start,
            version.fonte_url,
            diff.source_content_hash or version.content_hash,
        )
        effective = version.model_copy(update={"vigencia_inicio": start})
        if not _insert_device_version(conn, diff.norm_id, effective, event_id):
            raise DiffError(
                f"{device_id}: device version for event {event_id} already exists; "
                "refusing to drop the new text silently"
            )
        report.reindexed.append(device_id)

    if diff.removed:
        assert removed_end is not None
        for device_id in diff.removed:
            _close_removed(conn, device_id, removed_end)
            report.closed.append(device_id)

    return report
