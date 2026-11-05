"""Hydration by ``(device_id, norm_version_id)`` and citation resolution (RET-06).

The Qdrant payload never carries legal text: every candidate must be hydrated
from Postgres using the exact pair.  A missing pair is discarded and reported as
``incomplete_context``; a row from another version is rejected so norms and
versions can never cross-contaminate text.  ``RetrievedDevice.vigencia`` is
populated here — B7's fallback depends on it to emit citations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field

from src.contracts import Citation, InvalidCitation, RetrievedDevice, VigenciaStatus

_VALID_VIGENCIA = frozenset({"vigente", "alterado", "revogado", "cancelado", "superado"})


class HydrationRepo(Protocol):
    def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None: ...


class HydrationResult(BaseModel):
    devices: list[RetrievedDevice] = Field(default_factory=list)
    incomplete_context: list[tuple[str, int]] = Field(default_factory=list)

    @property
    def retrieved(self) -> list[RetrievedDevice]:
        return self.devices

    @property
    def hydrated(self) -> list[RetrievedDevice]:
        return self.devices

    @property
    def missing(self) -> list[tuple[str, int]]:
        return self.incomplete_context


def hydrate(
    pairs: Sequence[tuple[str, int] | RetrievedDevice],
    *,
    repo: HydrationRepo,
) -> HydrationResult:
    """Hydrate candidates strictly by pair, preserving score/source when available."""

    result = HydrationResult()
    seen: set[tuple[str, int]] = set()

    for entry in pairs:
        if isinstance(entry, RetrievedDevice):
            device_id, norm_version_id = entry.device_id, entry.norm_version_id
            score, source = entry.score, entry.source
        else:
            device_id, norm_version_id = entry
            score, source = 0.0, "bm25"

        key = (device_id, norm_version_id)
        if key in seen:
            continue
        seen.add(key)

        row = repo.get_device_version(device_id, norm_version_id)
        if not _row_matches(row, device_id, norm_version_id):
            result.incomplete_context.append(key)
            continue

        vigencia_raw = _field(row, "vigencia_status") or _field(row, "vigencia")
        if vigencia_raw is None:
            result.incomplete_context.append(key)
            continue
        vigencia = _valid_vigencia(vigencia_raw, device_id, norm_version_id)

        texto_literal = _field(row, "texto_literal")
        if texto_literal is None:
            texto_literal = _field(row, "texto")

        result.devices.append(
            RetrievedDevice(
                device_id=device_id,
                norm_version_id=norm_version_id,
                score=score,
                source=source,
                texto_literal=texto_literal or "",
                citacao=_field(row, "citacao") or "",
                vigencia=vigencia,
                contexto=_field(row, "contexto"),
                explicacao=_field(row, "explicacao"),
            )
        )
    return result


def resolve_citation(
    device_id: str,
    retrieved_version_id: int,
    *,
    repo: Any,
) -> Citation:
    """Build a citation from stored metadata; never trust the LLM with a version."""

    row = _fetch_row(repo, device_id, retrieved_version_id)
    if isinstance(row, Citation):
        if row.device_id != device_id or row.norm_version_id != retrieved_version_id:
            raise InvalidCitation(
                f"citation metadata does not match {device_id}@{retrieved_version_id}"
            )
        return row
    if not _row_matches(row, device_id, retrieved_version_id):
        raise InvalidCitation(f"no metadata for {device_id}@{retrieved_version_id}")

    citacao = _field(row, "citacao")
    texto = _field(row, "texto_literal")
    if texto is None:
        texto = _field(row, "texto")
    vigencia = _field(row, "vigencia_status") or _field(row, "vigencia")
    if not citacao or texto is None or vigencia is None:
        raise InvalidCitation(f"incomplete metadata for {device_id}@{retrieved_version_id}")
    vigencia = _valid_vigencia(vigencia, device_id, retrieved_version_id)

    return Citation(
        device_id=device_id,
        norm_version_id=retrieved_version_id,
        citacao=citacao,
        texto=texto,
        contexto=_field(row, "contexto") or "",
        vigencia=vigencia,
        fonte_url=_field(row, "fonte_url") or "",
    )


def _fetch_row(repo: Any, device_id: str, norm_version_id: int) -> Any | None:
    getter = getattr(repo, "get_device_version", None)
    if getter is not None:
        return getter(device_id, norm_version_id)
    getter = getattr(repo, "get_citation", None)
    if getter is not None:
        return getter(device_id, norm_version_id)
    return None


def _row_matches(row: Any, device_id: str, norm_version_id: int) -> bool:
    if row is None:
        return False
    row_device = _field(row, "device_id")
    if row_device is not None and row_device != device_id:
        return False
    row_version = _field(row, "norm_version_id")
    if row_version is not None and int(row_version) != norm_version_id:
        return False
    return True


def _field(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _valid_vigencia(value: Any, device_id: str, norm_version_id: int) -> VigenciaStatus:
    if not isinstance(value, str) or value not in _VALID_VIGENCIA:
        raise InvalidCitation(f"invalid vigencia {value!r} for {device_id}@{norm_version_id}")
    return cast(VigenciaStatus, value)
