"""Deduplicate by article and expand a leaf to its article context (RET-05).

Deduplication never lets ten chunks of the same article occupy the context: it
keeps the best-scoring leaf per ``(artigo_id, norm_version_id)`` with a
deterministic ``device_id`` tie-break.  Different versions of the same article
stay independent so a historical ``data_fato`` query never loses the version
that applies to it.  Expansion swaps only the context (full article) while
keeping the leaf's identity, score and citation; a lookup miss degrades safely
and reports ``incomplete_context`` instead of inventing text.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field

from src.contracts import RetrievedDevice

logger = logging.getLogger(__name__)

_ARTIGO_RE = re.compile(r"^(.*?/art[^/]+)")

ArticleVersionKey = tuple[str, int]


class ArticleLookup(Protocol):
    def lookup(self, artigo_id: str, norm_version_id: int) -> Any | None: ...


class ExpansionResult(BaseModel):
    devices: list[RetrievedDevice] = Field(default_factory=list)
    incomplete_context: list[ArticleVersionKey] = Field(default_factory=list)

    @property
    def expanded(self) -> list[RetrievedDevice]:
        return self.devices


def artigo_id(device_id: str) -> str:
    match = _ARTIGO_RE.match(device_id)
    return match.group(1) if match else device_id


def dedupe_by_artigo(
    candidates: Sequence[RetrievedDevice],
    *,
    max_per_article: int = 1,
) -> list[RetrievedDevice]:
    """Keep at most ``max_per_article`` devices per article *and version*.

    docs/05 §6.7 dedupes by article so ten chunks of one article cannot fill the
    context.  With ``max_per_article=1`` the most specific device wins: an
    article row beats its ``/cpt`` duplicate and a deeper paragraph/inciso/alinea
    beats the article; ties fall back to score and then to ``device_id``.

    ``max_per_article > 1`` keeps the highest scoring devices of the group
    instead.  The gold set is device-level, so the second paragraph of an
    article is a distinct device and a single slot per article silently drops
    it; the context budget, not the article count, should limit the list.
    """

    if max_per_article < 1:
        raise ValueError("max_per_article must be positive")

    groups: dict[ArticleVersionKey, list[RetrievedDevice]] = {}
    for candidate in candidates:
        key = (artigo_id(candidate.device_id), candidate.norm_version_id)
        groups.setdefault(key, []).append(candidate)

    selected: list[RetrievedDevice] = []
    for group in groups.values():
        if max_per_article == 1:
            specificity = max(_specificity(item.device_id) for item in group)
            eligible = [item for item in group if _specificity(item.device_id) == specificity]
            selected.append(min(eligible, key=lambda item: (-item.score, item.device_id)))
            continue
        ordered = sorted(group, key=lambda item: (-item.score, item.device_id))
        selected.extend(ordered[:max_per_article])
    return selected


def _specificity(device_id: str) -> int:
    """Rank article rows above their caput duplicate and below deeper leaves."""

    artigo = artigo_id(device_id)
    suffix = device_id[len(artigo) :].strip("/")
    if not suffix:
        return 1
    if suffix == "cpt":
        return 0
    return 2 + len(suffix.split("/"))


def expand_to_article(
    candidates: Sequence[RetrievedDevice],
    *,
    article_lookup: ArticleLookup | Callable[..., Any],
) -> ExpansionResult:
    """Attach the full article/caput text as context, never losing the leaf."""

    result = ExpansionResult()
    for candidate in candidates:
        artigo = artigo_id(candidate.device_id)
        article = _lookup(article_lookup, artigo, candidate.norm_version_id)
        article_text = _field(article, "texto_literal") or _field(article, "contexto")
        if not article_text:
            logger.warning(
                "incomplete_context: no article for %s@%s",
                candidate.device_id,
                candidate.norm_version_id,
            )
            result.incomplete_context.append((artigo, candidate.norm_version_id))
            result.devices.append(candidate)
            continue
        result.devices.append(
            candidate.model_copy(
                update={"contexto": _merge_context(candidate.contexto, article_text)}
            )
        )
    return result


def _merge_context(existing: str | None, article_text: str) -> str:
    """Keep the leaf context and add the full article/caput text once."""

    current = (existing or "").strip()
    article = str(article_text).strip()
    if not current:
        return article
    if not article or article in current:
        return current
    if current in article:
        return article
    return f"{current}\n\n{article}"


def _is_better(candidate: RetrievedDevice, current: RetrievedDevice) -> bool:
    if candidate.score != current.score:
        return candidate.score > current.score
    return candidate.device_id < current.device_id


_ARTICLE_PARAMS = frozenset({"artigo_id", "artigo", "article_id", "article"})
_VERSION_PARAMS = frozenset({"norm_version_id", "version", "versao", "norm_version", "v"})


def _lookup(
    lookup: ArticleLookup | Callable[..., Any],
    artigo: str,
    norm_version_id: int,
) -> Any | None:
    method = getattr(lookup, "lookup", None)
    target = method if method is not None else cast(Callable[..., Any], lookup)
    names, varargs = _signature_shape(target)
    if names is None:
        raise TypeError(
            "cannot inspect article_lookup signature; declare it as "
            "lookup(artigo_id, norm_version_id) or lookup(artigo_id)"
        )
    if varargs:
        raise TypeError(
            "ambiguous article_lookup signature: variadic callables are not supported; "
            "declare lookup(artigo_id, norm_version_id) or lookup(artigo_id)"
        )

    if not names:
        return target()
    first = names[0]
    if first in _ARTICLE_PARAMS:
        if len(names) == 1:
            return target(artigo)
        if len(names) == 2 and names[1] in _VERSION_PARAMS:
            return target(artigo, norm_version_id)
        raise _ambiguous_lookup(names)
    raise _ambiguous_lookup(names)


def _ambiguous_lookup(names: list[str]) -> TypeError:
    return TypeError(
        "ambiguous article_lookup signature: positional parameters are "
        f"{names!r}; name the first 'artigo_id'/'artigo' and the second "
        "'norm_version_id'/'version'"
    )


def _signature_shape(func: Any) -> tuple[list[str] | None, bool]:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return None, False
    names: list[str] = []
    varargs = False
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            names.append(parameter.name)
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            varargs = True
    return names, varargs


def _field(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)
