"""Citation rendering and context assembly with a token budget (RET-06).

Citations are rendered by the system, never by the LLM.  ``render_context``
orders sources by legal weight (constitution/law > súmula/tese > CNJ/CNMP >
doutrina), never truncates the literal text and caps the explanation at 200
tokens.  When the budget is exceeded, the lowest-priority entries are dropped
whole, preserving the literal of everything that stays.
"""

from __future__ import annotations

import re

from src.contracts import Citation
from src.index.chunk import estimate_tokens
from src.textnorm import strip_accents

MAX_EXPLANATION_TOKENS = 200
MAX_CONTEXT_TOKENS = 6000

_LAW_RE = re.compile(
    r"\b(constituicao|lei|codigo|decreto|estatuto|medida provisoria|emenda constitucional)\b"
)
_SUMULA_RE = re.compile(r"\b(sumula|tese|precedente|jurisprudencia|acordao)\b")
_CNJ_RE = re.compile(r"\b(cnj|cnmp)\b")


def render_citation(citation: Citation) -> str:
    """Render the canonical bracket format, e.g. ``[Lei nº 11.340/2006, art. 22]``."""

    text = citation.citacao.strip()
    if text.startswith("[") and text.endswith("]"):
        return text
    return f"[{text}]"


def render_context(
    citations: list[Citation],
    *,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> str:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    ordered = sorted(
        enumerate(citations),
        key=lambda item: (_priority(item[1]), item[0]),
    )
    entries = [_entry_text(citation) for _, citation in ordered]

    while len(entries) > 1 and _tokens("\n\n".join(entries)) > max_tokens:
        entries.pop()

    return "\n\n".join(entries)


def _entry_text(citation: Citation) -> str:
    parts = [render_citation(citation), citation.texto]
    explanation = _cap_tokens(citation.contexto, MAX_EXPLANATION_TOKENS)
    if explanation:
        parts.append(explanation)
    return "\n".join(parts)


def _priority(citation: Citation) -> int:
    normalized = strip_accents(citation.citacao).lower()
    if _SUMULA_RE.search(normalized):
        return 1
    if _CNJ_RE.search(normalized):
        return 2
    if _LAW_RE.search(normalized):
        return 0
    return 3


def _cap_tokens(text: str, max_tokens: int) -> str:
    text = text.strip()
    if not text or estimate_tokens(text) <= max_tokens:
        return text
    words = text.split()
    while words and estimate_tokens(" ".join(words)) > max_tokens:
        words.pop()
    return " ".join(words)


def _tokens(text: str) -> int:
    return estimate_tokens(text)
