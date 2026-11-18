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

# The STJ PDF prefixes each heading with a link glyph on its own baseline, so
# the line reads "G SÚMULA 542".  Requiring the line to *start* with SÚMULA
# found 6 enunciados out of 676; allowing that single-letter prefix finds all
# 641 headings plus the 35 marked as cancelled.
# A heading is the whole line: the glyph, the word, the number and at most a
# parenthetical.  Without that anchor, a wrapped sentence that happens to
# start with "Súmula 142 do STJ (...)" is read as a new enunciado and the
# parse produces duplicate ids (142, 408, 418, 469, 560).
_SUMULA_RE = re.compile(
    r"^\s*(?:[A-Z]\s+)?S[ÚU]MULA\s+(?:N[.º°]*\s*)?(\d+)\b\s*(\([^)]*\))?\s*$",
    re.IGNORECASE,
)
#: Detects a cancelled enunciado in any of the shapes the source uses:
#: "(Cancelada)", "(SÚMULA CANCELADA)" in the heading and the inline
#: "SÚMULA CANCELADA: ..." paragraph that explains the cancellation.
_CANCEL_RE = re.compile(
    r"(?:"
    r"\(\s*cancelad[ao][^)]*\)"
    r"|\(\s*S[ÚU]MULA\s+cancelad[ao][^)]*\)"
    r"|\bS[ÚU]MULA\s+cancelad[ao]\b"
    r"|\bcancelad[ao]\b\.?"
    r")",
    re.IGNORECASE,
)
#: Only the parenthetical annotations are removed from the literal; the
#: inline rationale is kept, because deleting the words would leave the
#: sentence starting with ": A Segunda Seção ...".
_CANCEL_ANNOTATION_RE = re.compile(
    r"\(\s*(?:S[ÚU]MULA\s+)?cancelad[ao][^)]*\)",
    re.IGNORECASE,
)
#: Extraction noise of the PDF, never part of an enunciado.
_NOISE_RE = re.compile(
    r"^(?:veja\s+mais|\d{1,3}|scon\.stj\.jus\.br.*|www\.stj\.jus\.br.*)$",
    re.IGNORECASE,
)
_SUMULA_EPOCH = date(1989, 1, 1)


def _parse_sumulas_text(source_id: str, text: str, document: Path) -> ParseResult:
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
        if not line or line.startswith("#") or _NOISE_RE.match(line):
            continue

        header = _SUMULA_RE.match(line)
        if header is not None:
            flush()
            current_number = int(header.group(1))
            rest = collapse_whitespace(header.group(2) or "")
            if _CANCEL_RE.search(rest):
                current_cancelled = True
                rest = collapse_whitespace(_CANCEL_ANNOTATION_RE.sub("", rest))
            if rest:
                current_lines.append(rest)
            continue

        if current_number is None:
            continue

        if _CANCEL_RE.search(line):
            current_cancelled = True
            line = collapse_whitespace(_CANCEL_ANNOTATION_RE.sub("", line))
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


def _extract_pdf_text(document: Path) -> str:
    import pymupdf

    try:
        pdf = pymupdf.open(document)
    except Exception as exc:  # pragma: no cover - depends on the PDF engine
        raise ParseError(f"could not open PDF {document}: {exc}") from exc
    try:
        pages = (pdf.load_page(index).get_text("text") for index in range(pdf.page_count))
        return "\n".join(pages)
    finally:
        pdf.close()


def parse_sumulas(source_id: str, path: str | Path) -> ParseResult:
    document = Path(path)
    raw = document.read_bytes()
    if not raw.strip():
        raise ParseError(f"{source_id}: empty document")

    if document.suffix.lower() == ".pdf" or raw[:4] == b"%PDF":
        text = _extract_pdf_text(document)
    else:
        text = raw.decode(detect_charset(raw), errors="replace")
    return _parse_sumulas_text(source_id, text, document)


def parse_sumulas_pdf(source_id: str, path: str | Path) -> ParseResult:
    document = Path(path)
    if not document.read_bytes().strip():
        raise ParseError(f"{source_id}: empty document")
    text = _extract_pdf_text(document)
    return _parse_sumulas_text(source_id, text, document)
