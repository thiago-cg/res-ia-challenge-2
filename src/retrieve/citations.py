"""Explicit citation parsing and resolution (RET-01)."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from src.contracts import CitationResolution
from src.textnorm import normalize_citation_forms, roman_to_int

_NORM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcpp\b|\bcodigo de processo penal\b"), "cpp"),
    (re.compile(r"\bcp\b|\bcodigo penal\b"), "cp"),
    (re.compile(r"\bcf\b|\bconstituicao\b"), "cf"),
    (
        re.compile(r"\blmp\b|\bmaria da penha\b|\blei 11\.?340\b|\b11\.?340\b"),
        "lmp",
    ),
)

_ARTICLE_RE = re.compile(r"\bartigo\s+(\d+)(?:-([a-z]))?\b")
_PUNCTUATION = "\"'“”().,"


@dataclass(frozen=True)
class ParsedCitation:
    raw: str
    norm_hint: str | None = None
    artigo: int | None = None
    artigo_sufixo: str | None = None
    paragrafo: int | None = None
    inciso: int | None = None
    alinea: str | None = None
    item: int | None = None


class CitationCatalog(Protocol):
    def find(self, norm_id: str, artigo_id: str) -> object | None: ...


def detect_norm_hint(text: str) -> str | None:
    normalized = normalize_citation_forms(text)
    for pattern, norm_id in _NORM_PATTERNS:
        if pattern.search(normalized):
            return norm_id
    return None


def _extract_number(text: str, keyword: str) -> int | None:
    match = re.search(rf"\b{keyword}\s+(\d+)\b", text)
    return int(match.group(1)) if match else None


def _extract_letter(text: str, keyword: str) -> str | None:
    match = re.search(rf"\b{keyword}\s+([a-z])\b", text)
    return match.group(1) if match else None


def _extract_bare_tokens(
    text: str, inciso: int | None, alinea: str | None
) -> tuple[int | None, str | None]:
    if inciso is not None and alinea is not None:
        return inciso, alinea

    for raw_token in text.split():
        token = raw_token.strip(_PUNCTUATION)
        if not token or token in {"artigo", "paragrafo", "inciso", "alinea", "item"}:
            continue
        if inciso is None:
            number = roman_to_int(token)
            if number is not None:
                inciso = number
                continue
        if alinea is None and len(token) == 1 and token.isalpha():
            alinea = token
    return inciso, alinea


def parse_citation(text: str) -> ParsedCitation:
    """Parse a citation such as ``art. 22, III, "b"``."""
    normalized = normalize_citation_forms(text)
    norm_hint = detect_norm_hint(normalized)

    artigo: int | None = None
    sufixo: str | None = None
    remainder = normalized
    match = _ARTICLE_RE.search(normalized)
    if match:
        artigo = int(match.group(1))
        sufixo = match.group(2)
        remainder = f"{normalized[: match.start()]} {normalized[match.end() :]}"

    paragrafo = _extract_number(remainder, "paragrafo")
    inciso = _extract_number(remainder, "inciso")
    alinea = _extract_letter(remainder, "alinea")
    item = _extract_number(remainder, "item")
    inciso, alinea = _extract_bare_tokens(remainder, inciso, alinea)

    return ParsedCitation(
        raw=text,
        norm_hint=norm_hint,
        artigo=artigo,
        artigo_sufixo=sufixo,
        paragrafo=paragrafo,
        inciso=inciso,
        alinea=alinea,
        item=item,
    )


def _artigo_id(norm_id: str, parsed: ParsedCitation) -> str:
    suffix = f"-{parsed.artigo_sufixo}" if parsed.artigo_sufixo else ""
    return f"{norm_id}/art{parsed.artigo}{suffix}"


def _hit_field(hit: object, name: str) -> Any:
    if isinstance(hit, dict):
        return hit.get(name)
    return getattr(hit, name, None)


def resolve_explicit_citation(
    text: str,
    *,
    catalog: CitationCatalog | None = None,
    norm_hint: str | None = None,
    data_fato: date | None = None,
) -> CitationResolution:
    """Resolve an explicit citation to a device.

    ``catalog=None`` resolves by syntax only and never fakes a hit. A citation to an
    inexistent or out-of-corpus article returns ``resolved=False``/``not_found``; the
    caller must abstain instead of falling back to hybrid search. ``data_fato`` is
    reserved for version selection and is not used by the current catalog protocol.
    """
    parsed = parse_citation(text)
    norm_id = norm_hint or parsed.norm_hint

    if parsed.artigo is None:
        has_device_hint = any(
            value is not None
            for value in (parsed.paragrafo, parsed.inciso, parsed.alinea, parsed.item)
        )
        if not has_device_hint:
            return CitationResolution(resolved=False, reason="no_citation")
        reason = "norm_ambiguous" if norm_id is None else "article_missing"
        return CitationResolution(resolved=False, ambiguous=True, reason=reason)

    if norm_id is None:
        return CitationResolution(resolved=False, ambiguous=True, reason="norm_ambiguous")

    artigo_id = _artigo_id(norm_id, parsed)

    if catalog is None:
        return CitationResolution(
            resolved=False, norm_id=norm_id, artigo_id=artigo_id, reason="no_catalog"
        )

    hit = catalog.find(norm_id, artigo_id)
    if hit is None:
        return CitationResolution(
            resolved=False, norm_id=norm_id, artigo_id=artigo_id, reason="not_found"
        )

    device_id = _hit_field(hit, "device_id")
    if not device_id:
        return CitationResolution(
            resolved=False, norm_id=norm_id, artigo_id=artigo_id, reason="not_found"
        )

    return CitationResolution(
        resolved=True,
        device_id=device_id,
        norm_id=_hit_field(hit, "norm_id") or norm_id,
        artigo_id=_hit_field(hit, "artigo_id") or artigo_id,
    )
