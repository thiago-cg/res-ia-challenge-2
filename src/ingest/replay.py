"""Replay parsed JSONL corpora into Postgres for local benchmarks.

The production ingest CLI validates every source before loading.  Some large
compiled sources (CP/CPP) still emit duplicate devices and overlapping
versions; this replay path keeps the load deterministic for the benchmark while
the validation debt remains visible.  It never invents text: every row comes
from ``data/processed/*.jsonl`` or a curated seed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from src.contracts import Device, DeviceType, DeviceVersion, VigenciaStatus
from src.index.load_db import LoadReport, load_parse_result
from src.ingest.models import Norm, ParseResult


def parse_result_from_jsonl(path: str | Path) -> ParseResult:
    """Build a ``ParseResult`` from one parser JSONL file."""

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        import json

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(payload)
    if not rows:
        raise ValueError(f"{path}: empty corpus")

    norm = Norm.model_validate(rows[0]["norm"])
    devices: dict[str, Device] = {}
    versions: list[DeviceVersion] = []
    for row in rows:
        device = Device(
            id=str(row["device_id"]),
            norm_id=str(row["norm_id"]),
            parent_id=row.get("parent_id"),
            artigo_id=str(row["artigo_id"]),
            tipo=cast(DeviceType, str(row["tipo"])),
            rotulo=str(row["rotulo"]),
            caminho=str(row["caminho"]),
            ordem=int(row["ordem"]),
        )
        devices.setdefault(device.id, device)
        versions.append(
            DeviceVersion(
                device_id=device.id,
                norm_version_id=int(row.get("norm_version_id") or 1),
                texto_literal=str(row["texto_literal"]),
                texto_anterior=row.get("texto_anterior"),
                contexto=str(row["contexto"]),
                citacao=str(row["citacao"]),
                vigencia_status=cast(VigenciaStatus, str(row["vigencia_status"])),
                redacao_dada_por=row.get("redacao_dada_por"),
                vigencia_inicio=_required_date(row["vigencia_inicio"]),
                vigencia_fim=_date(row["vigencia_fim"]),
                fonte_url=str(row.get("fonte_url") or ""),
                content_hash=str(row.get("content_hash") or ""),
                qdrant_point_id=UUID(str(row["qdrant_point_id"])),
                search_text=str(row.get("search_text") or ""),
            )
        )
    versions = [
        version
        for version in versions
        if version.vigencia_fim is None or version.vigencia_fim >= version.vigencia_inicio
    ]
    return ParseResult(
        norm=norm,
        devices=sorted(devices.values(), key=lambda item: item.ordem),
        versions=versions,
    )


def drop_missing_parents(result: ParseResult) -> ParseResult:
    """Drop devices whose parent is absent, plus their descendants."""

    by_id = {device.id: device for device in result.devices}
    valid: set[str] = set()
    changed = True
    while changed:
        changed = False
        for device in by_id.values():
            if device.id in valid:
                continue
            if device.parent_id is None or device.parent_id in valid:
                valid.add(device.id)
                changed = True
    return result.model_copy(
        update={
            "devices": [device for device in result.devices if device.id in valid],
            "versions": [version for version in result.versions if version.device_id in valid],
        }
    )


def load_jsonl_corpus(
    conn: Any,
    paths: Iterable[str | Path],
    *,
    drop_invalid_parents: bool = True,
) -> list[LoadReport]:
    """Load every JSONL file in order, returning one report per source."""

    reports: list[LoadReport] = []
    for path in paths:
        result = parse_result_from_jsonl(path)
        if drop_invalid_parents:
            result = drop_missing_parents(result)
        reports.append(load_parse_result(conn, result))
    return reports


def _required_date(value: Any) -> date:
    parsed = _date(value)
    if parsed is None:
        raise ValueError("vigencia_inicio is required")
    return parsed


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


__all__: Sequence[str] = (
    "drop_missing_parents",
    "load_jsonl_corpus",
    "parse_result_from_jsonl",
)
