"""Idempotent loading of parsed devices into PostgreSQL.

The loader never updates ``device_versions`` text: a changed device is a new
row created by :mod:`src.ingest.diff`. Here, collisions on the natural keys are
ignored so re-running the same parse result is a no-op.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.contracts import Device, DeviceVersion
from src.ingest import models
from src.ingest.models import Norm, ParseResult
from src.ingest.normalize import build_search_text, normalize_parse_result

IngestStatus = Literal["running", "ok", "error"]


class LoadReport(BaseModel):
    norm_id: str
    norm_version_ids: dict[str, int] = Field(default_factory=dict)
    devices_loaded: int = 0
    versions_loaded: int = 0
    versions_skipped: int = 0


def _norm_params(norm: Norm) -> tuple[object, ...]:
    return (
        norm.id,
        norm.tipo,
        norm.numero,
        norm.ano,
        norm.apelido,
        norm.ementa,
        norm.urn_lexml,
        norm.fonte_url or "",
    )


def _upsert_norm(conn: Any, norm: Norm) -> None:
    sql = """
        INSERT INTO norms (id, tipo, numero, ano, apelido, ementa, urn_lexml, fonte_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, _norm_params(norm))


def _upsert_device(conn: Any, device: Device) -> None:
    sql = """
        INSERT INTO devices (id, norm_id, parent_id, artigo_id, tipo, rotulo, caminho, ordem)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            parent_id = EXCLUDED.parent_id,
            artigo_id = EXCLUDED.artigo_id,
            tipo = EXCLUDED.tipo,
            rotulo = EXCLUDED.rotulo,
            caminho = EXCLUDED.caminho,
            ordem = EXCLUDED.ordem
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                device.id,
                device.norm_id,
                device.parent_id,
                device.artigo_id,
                device.tipo,
                device.rotulo,
                device.caminho,
                device.ordem,
            ),
        )


def source_content_hash(norm: Norm, versions: Sequence[DeviceVersion]) -> str:
    """Hash of the source snapshot: norm plus every parsed device hash.

    Both the initial load and the diff path use this same function, so the
    provenance hash does not depend on device order or on which path wrote it.
    """
    payload = json.dumps(
        {
            "norm_id": norm.id,
            "devices": sorted(
                f"{version.device_id}:{version.content_hash}" for version in versions
            ),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_norm_version(
    conn: Any,
    norm_id: str,
    vigencia_inicio: date,
    fonte_url: str,
    content_hash: str,
) -> int:
    """Append a norm event once; never mutate an existing provenance row."""
    insert_sql = """
        INSERT INTO norm_versions (norm_id, vigencia_inicio, fonte_url, content_hash)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (norm_id, vigencia_inicio) DO NOTHING
        RETURNING id
    """
    select_sql = """
        SELECT id FROM norm_versions
        WHERE norm_id = %s AND vigencia_inicio = %s
    """
    with conn.cursor() as cur:
        cur.execute(insert_sql, (norm_id, vigencia_inicio, fonte_url, content_hash))
        row = cur.fetchone()
        if row is None:
            cur.execute(select_sql, (norm_id, vigencia_inicio))
            row = cur.fetchone()
    if row is None:  # pragma: no cover - row exists after a conflict
        raise RuntimeError(f"could not find norm_version {norm_id}@{vigencia_inicio}")
    return int(row[0])


def _insert_device_version(
    conn: Any,
    norm_id: str,
    version: DeviceVersion,
    norm_version_id: int,
) -> bool:
    search_text = version.search_text or build_search_text(
        version.contexto, version.texto_literal, version.citacao
    )
    point_id = models.qdrant_point_id(version.device_id, norm_version_id)
    sql = """
        INSERT INTO device_versions (
            device_id, norm_id, norm_version_id, texto_literal, texto_anterior,
            contexto, citacao, vigencia_status, redacao_dada_por,
            vigencia_inicio, vigencia_fim, fonte_url, content_hash,
            qdrant_point_id, search_text
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_id, norm_version_id) DO NOTHING
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                version.device_id,
                norm_id,
                norm_version_id,
                version.texto_literal,
                version.texto_anterior,
                version.contexto,
                version.citacao,
                version.vigencia_status,
                version.redacao_dada_por,
                version.vigencia_inicio,
                version.vigencia_fim,
                version.fonte_url,
                version.content_hash,
                str(point_id),
                search_text,
            ),
        )
        row = cur.fetchone()
    return row is not None


def load_parse_result(
    conn: Any,
    result: ParseResult,
    *,
    ingest_run_id: int | None = None,
) -> LoadReport:
    """Load norm identity, events, devices and current texts idempotently."""
    normalized = normalize_parse_result(result)
    report = LoadReport(norm_id=normalized.norm.id)

    _upsert_norm(conn, normalized.norm)
    event_hash = source_content_hash(normalized.norm, normalized.versions)

    grouped: dict[date, list[DeviceVersion]] = defaultdict(list)
    for version in normalized.versions:
        grouped[version.vigencia_inicio].append(version)

    norm_version_ids: dict[date, int] = {}
    for vigencia_inicio, versions in sorted(grouped.items()):
        fonte_url = versions[0].fonte_url or normalized.norm.fonte_url
        norm_version_ids[vigencia_inicio] = _ensure_norm_version(
            conn,
            normalized.norm.id,
            vigencia_inicio,
            fonte_url,
            event_hash,
        )
    report.norm_version_ids = {
        vigencia.isoformat(): version_id for vigencia, version_id in norm_version_ids.items()
    }

    for device in normalized.devices:
        _upsert_device(conn, device)
        report.devices_loaded += 1

    for version in normalized.versions:
        inserted = _insert_device_version(
            conn,
            normalized.norm.id,
            version,
            norm_version_ids[version.vigencia_inicio],
        )
        if inserted:
            report.versions_loaded += 1
        else:
            report.versions_skipped += 1

    if ingest_run_id is not None:
        _update_ingest_run_counts(
            conn,
            ingest_run_id,
            devices_seen=len(normalized.devices),
            devices_changed=report.versions_loaded,
        )

    return report


def load_current_versions(conn: Any, norm_id: str) -> list[dict[str, Any]]:
    """Read one current row per device for ``norm_id``.

    The date/status window matches the retrieval default, so the ingest CLI
    diffs against exactly the rows a ``data_fato=None`` query would consider.
    Rows may come back as mappings (``dict_row``) or tuples.
    """

    sql = """
        SELECT DISTINCT ON (dv.device_id)
               dv.device_id,
               dv.content_hash,
               dv.norm_id,
               dv.vigencia_inicio
        FROM device_versions dv
        WHERE dv.norm_id = %s
          AND dv.vigencia_status IN ('vigente', 'alterado')
          AND dv.vigencia_inicio <= CURRENT_DATE
          AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= CURRENT_DATE)
        ORDER BY dv.device_id, dv.vigencia_inicio DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (norm_id,))
        rows = cur.fetchall()

    return [_current_row(row) for row in rows]


def _current_row(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {
            "device_id": row.get("device_id"),
            "content_hash": row.get("content_hash"),
            "norm_id": row.get("norm_id"),
            "vigencia_inicio": row.get("vigencia_inicio"),
        }
    values = list(row)
    if len(values) < 4:
        raise ValueError(f"unsupported current-version row: {row!r}")
    return {
        "device_id": values[0],
        "content_hash": values[1],
        "norm_id": values[2],
        "vigencia_inicio": values[3],
    }


def _update_ingest_run_counts(
    conn: Any,
    ingest_run_id: int,
    *,
    devices_seen: int,
    devices_changed: int,
) -> None:
    sql = """
        UPDATE ingest_runs
        SET devices_seen = %s, devices_changed = %s
        WHERE id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (devices_seen, devices_changed, ingest_run_id))


def _infer_norm_id(device_id: str) -> str:
    return device_id.split("/", 1)[0]


def load_versions(
    conn: Any,
    versions: ParseResult | Sequence[DeviceVersion],
    *,
    norm_id: str | None = None,
) -> LoadReport:
    """Compatibility wrapper: norms and devices must already exist in the DB.

    This wrapper only writes ``norm_versions``/``device_versions``. Callers that
    have a full :class:`ParseResult` should use :func:`load_parse_result`, which
    also upserts ``norms`` and ``devices``.
    """
    if isinstance(versions, ParseResult):
        return load_parse_result(conn, versions)

    version_list = list(versions)
    resolved_norm = norm_id or (_infer_norm_id(version_list[0].device_id) if version_list else "")
    report = LoadReport(norm_id=resolved_norm)

    for version in version_list:
        event_norm = norm_id or _infer_norm_id(version.device_id)
        event_id = _ensure_norm_version(
            conn,
            event_norm,
            version.vigencia_inicio,
            version.fonte_url,
            version.content_hash,
        )
        report.norm_version_ids[version.vigencia_inicio.isoformat()] = event_id
        if _insert_device_version(conn, event_norm, version, event_id):
            report.versions_loaded += 1
        else:
            report.versions_skipped += 1

    return report


def record_ingest_run(
    conn: Any,
    source_id: str,
    status: IngestStatus,
    *,
    ingest_run_id: int | None = None,
    content_hash: str | None = None,
    devices_seen: int | None = None,
    devices_changed: int | None = None,
    error: str | None = None,
) -> int:
    """Create or finish an ``ingest_runs`` row and return its id."""
    params: tuple[Any, ...]
    if ingest_run_id is None:
        sql = """
            INSERT INTO ingest_runs (
                source_id, status, finished_at, content_hash,
                devices_seen, devices_changed, error
            ) VALUES (
                %s, %s, CASE WHEN %s = 'running' THEN NULL ELSE now() END,
                %s, %s, %s, %s
            )
            RETURNING id
        """
        params = (
            source_id,
            status,
            status,
            content_hash,
            devices_seen,
            devices_changed,
            error,
        )
    else:
        sql = """
            UPDATE ingest_runs SET
                status = %s,
                finished_at = CASE WHEN %s = 'running' THEN NULL ELSE now() END,
                content_hash = COALESCE(%s, content_hash),
                devices_seen = COALESCE(%s, devices_seen),
                devices_changed = COALESCE(%s, devices_changed),
                error = COALESCE(%s, error)
            WHERE id = %s
            RETURNING id
        """
        params = (
            status,
            status,
            content_hash,
            devices_seen,
            devices_changed,
            error,
            ingest_run_id,
        )

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if row is None:  # pragma: no cover - RETURNING always yields a row on success
        raise RuntimeError(f"could not record ingest run for {source_id}")
    return int(row[0])
