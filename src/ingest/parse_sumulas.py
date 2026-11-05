from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from src.contracts import Device, DeviceVersion
from src.ingest.fetch import detect_charset
from src.ingest.html_utils import collapse_whitespace
from src.ingest.models import (
    FRESH_NORM_VERSION_ID,
    ParseError,
    ParseResult,
    build_norm,
    compute_content_hash,
    default_vigencia_inicio,
    normalize_search_text,
    qdrant_point_id,
)

_SUMULA_RE = re.compile(
    r"^\s*S[ÚU]MULA\s+(?:N[ºO°]\s*)?(\d+)\b\s*(?:[-–—:]\s*)?(.*)$",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(r"\(\s*cancelad[ao]\s*\)", re.IGNORECASE)
_SUMULA_EPOCH = date(1989, 1, 1)


def parse_sumulas(source_id: str, path: str | Path) -> ParseResult:
    document = Path(path)
    raw = document.read_bytes()
    if not raw.strip():
        raise ParseError(f"{source_id}: empty document")

    text = raw.decode(detect_charset(raw), errors="replace")
    norm = build_norm(source_id)
    vigencia_inicio = default_vigencia_inicio(source_id)

    entries: list[tuple[int, list[str], bool]] = []
    current_number: int | None = None
    current_lines: list[str] = []
    current_cancelled = False

    def flush() -> None:
        nonlocal current_number, current_lines, current_cancelled
        if current_number is not None:
            entries.append((current_number, current_lines, current_cancelled))
        current_number = None
        current_lines = []
        current_cancelled = False

    for raw_line in text.splitlines():
        line = collapse_whitespace(raw_line)
        if not line or line.startswith("#"):
            continue

        header = _SUMULA_RE.match(line)
        if header is not None:
            flush()
            current_number = int(header.group(1))
            rest = collapse_whitespace(header.group(2))
            if _CANCEL_RE.search(rest):
                current_cancelled = True
                rest = collapse_whitespace(_CANCEL_RE.sub("", rest))
            if rest:
                current_lines.append(rest)
            continue

        if current_number is None:
            continue

        if _CANCEL_RE.search(line):
            current_cancelled = True
            line = collapse_whitespace(_CANCEL_RE.sub("", line))
        if line:
            current_lines.append(line)

    flush()

    if not entries:
        raise ParseError(f"{source_id}: no sumula found in {document}")

    context_title = norm.apelido or norm.id
    devices: list[Device] = []
    versions: list[DeviceVersion] = []
    warnings: list[str] = []

    for ordem, (number, lines, cancelled) in enumerate(entries, start=1):
        device_id = f"stj-sum-{number}"
        literal = collapse_whitespace(" ".join(lines))
        if not literal:
            warnings.append(f"{device_id}: empty literal text was not indexed")
            continue

        status = "cancelado" if cancelled else "vigente"
        vigencia_fim = _SUMULA_EPOCH if cancelled else None
        rotulo = f"Súmula nº {number}"
        caminho = f"Súmula {number}"
        contexto = f"{context_title}\n{rotulo}"
        citacao = f"Súmula nº {number} do STJ"
        search_text = normalize_search_text(f"{contexto}\n{literal}")
        content_hash = compute_content_hash(
            device_id=device_id,
            artigo_id=device_id,
            parent_id=None,
            tipo="artigo",
            rotulo=rotulo,
            caminho=caminho,
            contexto=contexto,
            citacao=citacao,
            texto_literal=literal,
            texto_anterior=None,
            vigencia_status=status,
            redacao_dada_por=None,
            vigencia_inicio=vigencia_inicio,
            vigencia_fim=vigencia_fim,
            fonte_url=norm.fonte_url,
        )

        devices.append(
            Device(
                id=device_id,
                norm_id=norm.id,
                parent_id=None,
                artigo_id=device_id,
                tipo="artigo",
                rotulo=rotulo,
                caminho=caminho,
                ordem=ordem,
            )
        )
        versions.append(
            DeviceVersion(
                device_id=device_id,
                norm_version_id=FRESH_NORM_VERSION_ID,
                texto_literal=literal,
                texto_anterior=None,
                contexto=contexto,
                citacao=citacao,
                vigencia_status=status,  # type: ignore[arg-type]
                redacao_dada_por=None,
                vigencia_inicio=vigencia_inicio,
                vigencia_fim=vigencia_fim,
                fonte_url=norm.fonte_url,
                content_hash=content_hash,
                qdrant_point_id=qdrant_point_id(device_id),
                search_text=search_text,
            )
        )

    return ParseResult(norm=norm, devices=devices, versions=versions, warnings=warnings)
