"""Explicit citation parsing and resolution (RET-01)."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from src.contracts import CitationResolution
from src.textnorm import canonical_roman_to_int, normalize_citation_forms

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
_PAR_UNICO_RE = re.compile(r"\bparagrafo\s+unico\b")
_QUALIFIER_PATTERN = r"(?:paragrafo\s+(?:unico|\d+)|inciso\s+\d+|alinea\s+[a-z]|item\s+\d+)"
_QUALIFIER_CONNECTOR = r"(?:do|da|de|dos|das|no|na|em)"
_LEADING_QUALIFIERS_RE = re.compile(
    rf"(?:{_QUALIFIER_PATTERN}\s+{_QUALIFIER_CONNECTOR}\s+)*"
    rf"{_QUALIFIER_PATTERN}\s*(?:{_QUALIFIER_CONNECTOR}\s*)?$"
)
_PUNCTUATION = "\"'“”().,"

#: Structural words never taken as a bare qualifier value.
_CITATION_WORDS = frozenset({"artigo", "paragrafo", "inciso", "alinea", "item"})

#: Single letters that are ordinary Portuguese words, so never a bare alinea.
_PROSE_SINGLE_LETTERS = frozenset({"a", "e", "o"})

#: Words that give a bare Roman numeral or letter a citation meaning.
_CITATION_MARKER_RE = re.compile(r"\b(?:artigo|paragrafo|inciso|alinea|item|caput|sumula)\b")


@dataclass(frozen=True)
class ParsedCitation:
    raw: str
    norm_hint: str | None = None
    artigo: int | None = None
    artigo_sufixo: str | None = None
    paragrafo: int | None = None
    paragrafo_unico: bool = False
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
    """Read qualifiers written next to the article without a keyword.

    ``art. 22, III, "b"`` carries the inciso and the alinea as bare tokens, so this
    path has to exist.  It only accepts canonical Roman numerals and letters that
    are not Portuguese words: ``mim``, ``mil``, ``vim`` and ``vivi`` are valid runs
    of Roman letters, and reading them as an inciso made the pipeline abstain on
    questions such as "a acao depende de mim".
    """
    if inciso is not None and alinea is not None:
        return inciso, alinea

    for raw_token in text.split():
        token = raw_token.strip(_PUNCTUATION)
        if not token or token in _CITATION_WORDS:
            continue
        if inciso is None:
            number = canonical_roman_to_int(token)
            if number is not None:
                inciso = number
                continue
        if alinea is not None or len(token) != 1 or not token.isalpha():
            continue
        quoted = _is_quoted(raw_token)
        if quoted or (inciso is not None and token not in _PROSE_SINGLE_LETTERS):
            alinea = token
    return inciso, alinea


def _is_quoted(raw_token: str) -> bool:
    return any(char in raw_token for char in "\"'“”")


def _leading_qualifiers(text: str) -> str:
    """Return the qualifier chain immediately before the article reference.

    ``inciso IX do art. 22`` and ``alínea b do inciso III do art. 22`` carry the
    leaf *before* the article; stop at the first word that is not a qualifier or
    connector so surrounding prose is never parsed as part of the citation.
    """

    match = _LEADING_QUALIFIERS_RE.search(text)
    return match.group(0).strip() if match else ""


def _allows_bare_tokens(normalized: str, artigo: int | None) -> bool:
    """Bare qualifiers only carry meaning inside a citation.

    ``art. 22, III, "b"`` spells the inciso and the alinea with no keyword, so the
    bare tokens still have to be read next to an article reference.  On their own
    they are ordinary prose, and reading them turned "depende de mim" into inciso
    1999 -- an explicit citation miss, so the pipeline abstained on a question it
    could answer.
    """
    return artigo is not None or _CITATION_MARKER_RE.search(normalized) is not None


def parse_citation(text: str) -> ParsedCitation:
    """Parse a citation such as ``art. 22, III, "b"`` or ``inciso III do art. 22``."""
    normalized = normalize_citation_forms(text)
    norm_hint = detect_norm_hint(normalized)

    artigo: int | None = None
    sufixo: str | None = None
    remainder = normalized
    match = _ARTICLE_RE.search(normalized)
    if match:
        artigo = int(match.group(1))
        sufixo = match.group(2)
        leading = _leading_qualifiers(normalized[: match.start()])
        remainder = f"{leading} {normalized[match.end() :]}".strip()

    paragrafo = _extract_number(remainder, "paragrafo")
    paragrafo_unico = paragrafo is None and _PAR_UNICO_RE.search(remainder) is not None
    inciso = _extract_number(remainder, "inciso")
    alinea = _extract_letter(remainder, "alinea")
    item = _extract_number(remainder, "item")
    if _allows_bare_tokens(normalized, artigo):
        inciso, alinea = _extract_bare_tokens(remainder, inciso, alinea)

    return ParsedCitation(
        raw=text,
        norm_hint=norm_hint,
        artigo=artigo,
        artigo_sufixo=sufixo,
        paragrafo=paragrafo,
        paragrafo_unico=paragrafo_unico,
        inciso=inciso,
        alinea=alinea,
        item=item,
    )


def _artigo_id(norm_id: str, parsed: ParsedCitation) -> str:
    suffix = f"-{parsed.artigo_sufixo}" if parsed.artigo_sufixo else ""
    return f"{norm_id}/art{parsed.artigo}{suffix}"


def _device_id(norm_id: str, parsed: ParsedCitation) -> str:
    """Build the canonical leaf ID in parser order: cpt/par, inc, ali, item."""
    base = _artigo_id(norm_id, parsed)
    if parsed.artigo is None:
        return base

    parts = [base]
    if parsed.paragrafo_unico:
        parts.append("par-unico")
    elif parsed.paragrafo is not None:
        parts.append(f"par{parsed.paragrafo}")
    elif any(value is not None for value in (parsed.inciso, parsed.alinea, parsed.item)):
        parts.append("cpt")

    if parsed.inciso is not None:
        parts.append(f"inc{parsed.inciso}")
    if parsed.alinea is not None:
        parts.append(f"ali-{parsed.alinea}")
    if parsed.item is not None:
        parts.append(f"item-{parsed.item}")
    return "/".join(parts)


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
        has_device_hint = parsed.paragrafo_unico or any(
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
    device_id = _device_id(norm_id, parsed)

    if catalog is None:
        return CitationResolution(
            resolved=False, norm_id=norm_id, artigo_id=artigo_id, reason="no_catalog"
        )

    hit = catalog.find(norm_id, device_id)
    if hit is None:
        return CitationResolution(
            resolved=False, norm_id=norm_id, artigo_id=artigo_id, reason="not_found"
        )

    resolved_device_id = _hit_field(hit, "device_id")
    if not resolved_device_id:
        return CitationResolution(
            resolved=False, norm_id=norm_id, artigo_id=artigo_id, reason="not_found"
        )

    return CitationResolution(
        resolved=True,
        device_id=resolved_device_id,
        norm_id=_hit_field(hit, "norm_id") or norm_id,
        artigo_id=_hit_field(hit, "artigo_id") or artigo_id,
    )
