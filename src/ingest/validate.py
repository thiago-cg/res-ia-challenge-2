"""Validation checklist from docs/04 §12, applied before loading."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from src.contracts import Device, DeviceVersion
from src.ingest.models import ParseResult
from src.ingest.normalize import content_hash, has_struck_markup, version_metadata

CurrentStatus = Literal["vigente", "alterado"]


class ValidationReport(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sample_check: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_parse_result(
    result: ParseResult,
    *,
    max_length: int = 4000,
    expected_article_count: int | None = None,
    sample_checked: bool = False,
    split_device_ids: set[str] | None = None,
) -> ValidationReport:
    """Run the ingestion checklist and return errors and warnings.

    ``split_device_ids`` marks devices whose text was explicitly split into
    article blocks and therefore may exceed ``max_length``.
    """
    report = ValidationReport(sample_check=sample_checked)
    split_ids = split_device_ids or set()

    devices = {device.id: device for device in result.devices}
    if len(devices) != len(result.devices):
        report.errors.append("duplicate device ids in parse result")

    parents = {device.parent_id for device in result.devices if device.parent_id is not None}
    for device in result.devices:
        if device.parent_id is not None and device.parent_id not in devices:
            report.errors.append(
                f"{device.id}: parent_id {device.parent_id} does not exist as a device"
            )
        if device.artigo_id not in devices:
            report.errors.append(f"{device.id}: artigo_id {device.artigo_id} does not exist")
        if device.norm_id != result.norm.id:
            report.errors.append(
                f"{device.id}: norm_id {device.norm_id} does not match norm {result.norm.id}"
            )

    for device in result.devices:
        is_leaf = device.id not in parents
        if is_leaf and device.parent_id is None and device.tipo != "artigo":
            report.errors.append(f"{device.id}: leaf device has no parent_id")

    versions_by_device: dict[str, list[DeviceVersion]] = {}
    for version in result.versions:
        versions_by_device.setdefault(version.device_id, []).append(version)
        version_device = devices.get(version.device_id)
        if version_device is None:
            report.errors.append(f"{version.device_id}: version has no matching device identity")
            continue

        _validate_literal(
            report, version, version_device, max_length=max_length, split_ids=split_ids
        )
        _validate_citation(report, version, result)

        expected_hash = content_hash(
            version.texto_literal, version_metadata(version, version_device)
        )
        if expected_hash != version.content_hash:
            report.errors.append(
                f"{version.device_id}: content_hash is not stable for the current literal/metadata"
            )

    for device_id, versions in versions_by_device.items():
        current = [
            version
            for version in versions
            if version.vigencia_status in ("vigente", "alterado") and version.vigencia_fim is None
        ]
        for index, first in enumerate(current):
            for second in current[index + 1 :]:
                if _ranges_overlap(first, second):
                    report.errors.append(
                        f"{device_id}: overlapping current versions "
                        f"({first.vigencia_inicio} and {second.vigencia_inicio})"
                    )

    if expected_article_count is not None:
        article_ids = {device.id for device in result.devices if device.tipo == "artigo"}
        if len(article_ids) != expected_article_count:
            report.errors.append(
                f"article count {len(article_ids)} does not match the norm index "
                f"({expected_article_count})"
            )

    if not sample_checked:
        report.warnings.append("sample of 20 devices has not been manually checked")

    return report


def _validate_literal(
    report: ValidationReport,
    version: DeviceVersion,
    device: Device,
    *,
    max_length: int,
    split_ids: set[str],
) -> None:
    literal = version.texto_literal
    if not literal.strip():
        report.errors.append(f"{version.device_id}: empty texto_literal")
        return

    if has_struck_markup(literal):
        report.errors.append(f"{version.device_id}: struck text markup remains in texto_literal")
    elif version.texto_anterior and len(version.texto_anterior.strip()) >= 3:
        struck = version.texto_anterior.strip().lower()
        if struck in literal.lower():
            report.errors.append(f"{version.device_id}: struck text remains in texto_literal")

    if len(literal) > max_length and device.id not in split_ids:
        report.errors.append(
            f"{device.id}: texto_literal exceeds max_length {max_length} without an explicit split"
        )


def _validate_citation(
    report: ValidationReport,
    version: DeviceVersion,
    result: ParseResult,
) -> None:
    if not version.citacao.strip():
        report.errors.append(f"{version.device_id}: citation is empty")
    if not result.norm.id.strip():
        report.errors.append(f"{version.device_id}: citation does not resolve to a norm")
    if not version.fonte_url.strip() and not result.norm.fonte_url.strip():
        report.errors.append(f"{version.device_id}: citation has no source URL")


def _ranges_overlap(first: DeviceVersion, second: DeviceVersion) -> bool:
    first_end = first.vigencia_fim or date.max
    second_end = second.vigencia_fim or date.max
    return first.vigencia_inicio <= second_end and second.vigencia_inicio <= first_end
