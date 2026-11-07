"""Normalization of parsed devices for search and stable content hashes.

The citation grammar lives in :mod:`src.textnorm`; this module only composes
the search text produced by the parser and keeps hashing deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from src.contracts import Device, DeviceVersion
from src.ingest.models import ParseResult, close_version_windows, compute_content_hash
from src.textnorm import normalize_search_text

_NR_RE = re.compile(r"\(\s*NR\s*\)", re.IGNORECASE)
_STRUCK_MARKUP_RE = re.compile(r"</?(?:s|strike|del)>|~~", re.IGNORECASE)

_HASH_KEYS = (
    "device_id",
    "artigo_id",
    "parent_id",
    "tipo",
    "rotulo",
    "caminho",
    "contexto",
    "citacao",
    "texto_anterior",
    "vigencia_status",
    "redacao_dada_por",
    "vigencia_inicio",
    "vigencia_fim",
    "fonte_url",
)


def strip_nr(text: str) -> str:
    """Remove only the ``(NR)`` marker, preserving surrounding whitespace."""
    return _NR_RE.sub("", text)


def build_search_text(contexto: str, texto_literal: str, citacao: str) -> str:
    """Build normalized search text from context, literal and citation."""
    parts = [part for part in (contexto, texto_literal, citacao) if part]
    return normalize_search_text("\n".join(parts))


def version_metadata(version: DeviceVersion, device: Device | None = None) -> dict[str, Any]:
    """Return the deterministic metadata used by :func:`content_hash`."""
    return {
        "device_id": version.device_id,
        "artigo_id": device.artigo_id if device is not None else "",
        "parent_id": device.parent_id if device is not None else None,
        "tipo": device.tipo if device is not None else "",
        "rotulo": device.rotulo if device is not None else "",
        "caminho": device.caminho if device is not None else "",
        "contexto": version.contexto,
        "citacao": version.citacao,
        "texto_anterior": version.texto_anterior,
        "vigencia_status": version.vigencia_status,
        "redacao_dada_por": version.redacao_dada_por,
        "vigencia_inicio": version.vigencia_inicio,
        "vigencia_fim": version.vigencia_fim,
        "fonte_url": version.fonte_url,
    }


def _canonical_metadata(metadados: Mapping[str, Any] | str) -> str:
    if isinstance(metadados, str):
        return metadados
    return json.dumps(
        dict(metadados),
        sort_keys=True,
        ensure_ascii=False,
        default=_json_default,
        separators=(",", ":"),
    )


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def content_hash(texto_literal: str, metadados: Mapping[str, Any] | str) -> str:
    """Stable SHA-256 of literal text plus metadata.

    When the metadata carries every field used by the parser hash, delegate to
    :func:`src.ingest.models.compute_content_hash` so parser and loader agree.
    """
    if isinstance(metadados, Mapping) and all(key in metadados for key in _HASH_KEYS):
        return compute_content_hash(
            texto_literal=texto_literal,
            device_id=str(metadados["device_id"]),
            artigo_id=str(metadados["artigo_id"]),
            parent_id=_optional_str(metadados["parent_id"]),
            tipo=str(metadados["tipo"]),
            rotulo=str(metadados["rotulo"]),
            caminho=str(metadados["caminho"]),
            contexto=str(metadados["contexto"]),
            citacao=str(metadados["citacao"]),
            texto_anterior=_optional_str(metadados["texto_anterior"]),
            vigencia_status=str(metadados["vigencia_status"]),
            redacao_dada_por=_optional_str(metadados["redacao_dada_por"]),
            vigencia_inicio=_as_date(metadados["vigencia_inicio"]),
            vigencia_fim=_as_optional_date(metadados["vigencia_fim"]),
            fonte_url=str(metadados["fonte_url"]),
        )

    canonical = _canonical_metadata(metadados)
    payload = f"{strip_nr(texto_literal)}\n{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_optional_date(value: object) -> date | None:
    if value is None:
        return None
    return _as_date(value)


def has_struck_markup(text: str) -> bool:
    """Whether literal text still contains strikethrough markup."""
    return _STRUCK_MARKUP_RE.search(text) is not None


def normalize_parse_result(result: ParseResult) -> ParseResult:
    """Populate search text and recompute hashes without touching provenance."""
    devices = {device.id: device for device in result.devices}
    versions: list[DeviceVersion] = []

    for version in close_version_windows(result.versions):
        literal = strip_nr(version.texto_literal)
        device = devices.get(version.device_id)
        metadata = version_metadata(version, device)
        versions.append(
            version.model_copy(
                update={
                    "texto_literal": literal,
                    "search_text": build_search_text(version.contexto, literal, version.citacao),
                    "content_hash": content_hash(literal, metadata),
                }
            )
        )

    return result.model_copy(update={"versions": versions})
