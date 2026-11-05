"""Deduplicate by article and expand a leaf to its article context (RET-05).

Deduplication never lets ten chunks of the same article occupy the context: it
keeps the best-scoring leaf per ``artigo_id`` with a deterministic
``device_id`` tie-break.  Expansion swaps only the context (full article) while
keeping the leaf's identity, score and citation; a lookup miss degrades safely
and logs ``incomplete_context`` instead of inventing text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

from src.contracts import RetrievedDevice

logger = logging.getLogger(__name__)

_ARTIGO_RE = re.compile(r"^(.*?/art[^/]+)")


class ArticleLookup(Protocol):
    def lookup(self, artigo_id: str, norm_version_id: int) -> Any | None: ...


def artigo_id(device_id: str) -> str:
    match = _ARTIGO_RE.match(device_id)
    return match.group(1) if match else device_id


def dedupe_by_artigo(candidates: Sequence[RetrievedDevice]) -> list[RetrievedDevice]:
    """Keep one device per article: highest score, then smallest device_id."""

    best: dict[str, RetrievedDevice] = {}
    for candidate in candidates:
        key = artigo_id(candidate.device_id)
        current = best.get(key)
        if current is None or _is_better(candidate, current):
            best[key] = candidate
    return list(best.values())


def expand_to_article(
    candidates: Sequence[RetrievedDevice],
    *,
    article_lookup: ArticleLookup | Callable[..., Any],
) -> list[RetrievedDevice]:
    """Attach the full article/caput text as context, never losing the leaf."""

    expanded: list[RetrievedDevice] = []
    for candidate in candidates:
        article = _lookup(article_lookup, artigo_id(candidate.device_id), candidate.norm_version_id)
        article_text = _field(article, "texto_literal") or _field(article, "contexto")
        if not article_text:
            logger.warning(
                "incomplete_context: no article for %s@%s",
                candidate.device_id,
                candidate.norm_version_id,
            )
            expanded.append(candidate)
            continue
        expanded.append(candidate.model_copy(update={"contexto": article_text}))
    return expanded


def _is_better(candidate: RetrievedDevice, current: RetrievedDevice) -> bool:
    if candidate.score != current.score:
        return candidate.score > current.score
    return candidate.device_id < current.device_id


def _lookup(
    lookup: ArticleLookup | Callable[..., Any],
    artigo: str,
    norm_version_id: int,
) -> Any | None:
    method = getattr(lookup, "lookup", None)
    if method is not None:
        try:
            return method(artigo, norm_version_id)
        except TypeError:
            return method(artigo)
    call = cast(Callable[..., Any], lookup)
    try:
        return call(artigo, norm_version_id)
    except TypeError:
        return call(artigo)


def _field(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)
