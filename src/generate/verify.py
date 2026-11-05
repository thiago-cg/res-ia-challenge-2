"""Citation verifier (RET-07): deterministic checks plus an optional judge.

A deterministic failure rejects the citation and asks for one regeneration; a
semantic failure from the judge does the same.  After a persistent failure the
safe action is to abstain and show only the retrieved devices.  The verifier
never accepts an invented device ID or a version that was not retrieved.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from src.contracts import (
    Answer,
    Citation,
    InvalidCitation,
    RetrievedDevice,
    VerificationResult,
)
from src.retrieve.hydrate import resolve_citation

Judge = Callable[..., Any]

_QUOTE_RE = re.compile(r'"([^"]{4,})"|“([^”]{4,})”')


def verify(
    answer: Answer,
    retrieved: Sequence[RetrievedDevice],
    *,
    repo: Any | None = None,
    judge: Judge | None = None,
    attempt: int = 1,
    max_attempts: int = 2,
) -> VerificationResult:
    devices = list(retrieved)
    by_pair = {(item.device_id, item.norm_version_id): item for item in devices}
    devices_by_id: dict[str, list[RetrievedDevice]] = {}
    for item in devices:
        devices_by_id.setdefault(item.device_id, []).append(item)

    issues: list[str] = []

    for citation in answer.citacoes:
        issues.extend(_check_citation(citation, by_pair, devices_by_id, repo))

    issues.extend(_check_quotes(answer.resposta, devices, repo))
    issues.extend(_check_claim_has_citation(answer))

    semantic_issues: list[str] = []
    if judge is not None:
        semantic_issues = _run_judge(judge, answer, devices)

    deterministic_ok = not issues
    semantic_ok = None if judge is None else not semantic_issues
    all_issues = _dedupe(issues + semantic_issues)
    ok = deterministic_ok and semantic_ok is not False

    if ok:
        action: Literal["accept", "regenerate", "abstain"] = "accept"
    elif attempt >= max_attempts:
        action = "abstain"
    else:
        action = "regenerate"

    return VerificationResult(
        ok=ok,
        deterministic_ok=deterministic_ok,
        semantic_ok=semantic_ok,
        issues=all_issues,
        action=action,
    )


def _check_citation(
    citation: Citation,
    by_pair: Mapping[tuple[str, int], RetrievedDevice],
    devices_by_id: Mapping[str, list[RetrievedDevice]],
    repo: Any | None,
) -> list[str]:
    issues: list[str] = []
    pair = (citation.device_id, citation.norm_version_id)

    if pair not in by_pair:
        if citation.device_id in devices_by_id:
            issues.append(
                f"citation version mismatch: {citation.device_id}@{citation.norm_version_id} "
                "was not retrieved"
            )
        else:
            issues.append(f"citation device not retrieved: {citation.device_id}")

    if repo is not None:
        try:
            resolved = resolve_citation(citation.device_id, citation.norm_version_id, repo=repo)
        except InvalidCitation:
            issues.append(
                f"citation device not found: {citation.device_id}@{citation.norm_version_id}"
            )
        else:
            if resolved.citacao != citation.citacao:
                issues.append(
                    f"citation metadata mismatch for {citation.device_id}: "
                    "rendered citation does not match stored metadata"
                )

    return issues


def _check_quotes(
    resposta: str,
    retrieved: Sequence[RetrievedDevice],
    repo: Any | None,
) -> list[str]:
    quotes = [
        straight or curly
        for straight, curly in _QUOTE_RE.findall(resposta or "")
        if straight or curly
    ]
    if not quotes:
        return []

    literals = [_normalize_space(item.texto_literal) for item in retrieved]
    if repo is not None:
        for item in retrieved:
            row = _get_row(repo, item.device_id, item.norm_version_id)
            text = _row_field(row, "texto_literal")
            if text:
                literals.append(_normalize_space(text))

    issues: list[str] = []
    for quote in quotes:
        normalized = _normalize_space(quote)
        if not any(normalized in literal for literal in literals):
            issues.append(f'quoted text is outside the literal: "{quote}"')
    return issues


def _check_claim_has_citation(answer: Answer) -> list[str]:
    if answer.abstencao:
        return []
    if answer.resposta.strip() and not answer.citacoes:
        return ["legal claim without citation"]
    return []


def _run_judge(
    judge: Judge,
    answer: Answer,
    retrieved: list[RetrievedDevice],
) -> list[str]:
    try:
        result = judge(answer, retrieved)
    except TypeError:
        try:
            result = judge(answer.resposta, retrieved)
        except TypeError:
            result = judge(answer.resposta)
    return _normalize_judge_result(result)


def _normalize_judge_result(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, bool):
        return [] if result else ["unsupported claim"]
    if isinstance(result, str):
        return [result] if result.strip() else []
    if isinstance(result, Mapping):
        issues = result.get("issues")
        normalized = [str(item) for item in issues] if isinstance(issues, Sequence) else []
        if result.get("ok") is False and not normalized:
            normalized = ["unsupported claim"]
        return normalized
    if isinstance(result, Sequence):
        return [str(item) for item in result if str(item).strip()]
    return [str(result)]


def _get_row(repo: Any, device_id: str, norm_version_id: int) -> Any | None:
    getter = getattr(repo, "get_device_version", None)
    return getter(device_id, norm_version_id) if getter is not None else None


def _row_field(row: Any, name: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _normalize_space(text: str) -> str:
    return " ".join(text.split())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
