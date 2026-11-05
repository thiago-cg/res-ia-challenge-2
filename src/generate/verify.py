"""Citation verifier (RET-07): deterministic checks plus an optional judge.

A deterministic failure rejects the citation and asks for one regeneration; a
semantic failure from the judge does the same.  After a persistent failure the
safe action is to abstain and show only the retrieved devices.  The verifier
never accepts an invented device ID or a version that was not retrieved.
"""

from __future__ import annotations

import inspect
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
    hydrated_literal: str | None = None

    if pair not in by_pair:
        if citation.device_id in devices_by_id:
            issues.append(
                f"citation version mismatch: {citation.device_id}@{citation.norm_version_id} "
                "was not retrieved"
            )
        else:
            issues.append(f"citation device not retrieved: {citation.device_id}")
    else:
        retrieved_device = by_pair[pair]
        if retrieved_device.citacao and not _same_citation(
            retrieved_device.citacao, citation.citacao
        ):
            issues.append(
                f"citation metadata mismatch for {citation.device_id}: "
                "rendered citation does not match retrieved metadata"
            )
        if retrieved_device.texto_literal:
            hydrated_literal = retrieved_device.texto_literal

    if repo is not None:
        try:
            resolved = resolve_citation(citation.device_id, citation.norm_version_id, repo=repo)
        except InvalidCitation:
            issues.append(
                f"citation device not found: {citation.device_id}@{citation.norm_version_id}"
            )
        else:
            if not _same_citation(resolved.citacao, citation.citacao):
                issues.append(
                    f"citation metadata mismatch for {citation.device_id}: "
                    "rendered citation does not match stored metadata"
                )
            if resolved.texto:
                hydrated_literal = resolved.texto

    issues.extend(_check_citation_text(citation, hydrated_literal))
    return issues


def _check_citation_text(citation: Citation, hydrated_literal: str | None) -> list[str]:
    if not citation.texto.strip():
        return [f"citation text is empty for {citation.device_id}"]
    if hydrated_literal is None:
        return [f"citation literal unavailable for {citation.device_id}"]
    if _normalize_space(citation.texto) not in _normalize_space(hydrated_literal):
        return [f"citation text is not inside the hydrated literal for {citation.device_id}"]
    return []


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


_JUDGE_TEXT_PARAMS = frozenset({"resposta", "text", "texto", "claim", "afirmacao", "statement"})
_JUDGE_ANSWER_PARAMS = frozenset({"answer", "resposta_obj", "answer_obj"})


def _run_judge(
    judge: Judge,
    answer: Answer,
    retrieved: list[RetrievedDevice],
) -> list[str]:
    # Inspect once and dispatch by parameter name: ``TypeError`` raised inside
    # the judge propagates, and an ambiguous shape fails before any call.
    names, varargs = _signature_shape(judge)
    if names is None:
        raise TypeError(
            "cannot inspect judge signature; declare it as judge(answer, retrieved) "
            "or judge(resposta, retrieved)"
        )
    if varargs:
        raise TypeError(
            "ambiguous judge signature: variadic judges are not supported; declare "
            "judge(answer, retrieved) or judge(resposta, retrieved)"
        )

    if not names:
        result = judge()
    elif len(names) == 1:
        if names[0] in _JUDGE_TEXT_PARAMS:
            result = judge(answer.resposta)
        elif names[0] in _JUDGE_ANSWER_PARAMS:
            result = judge(answer)
        else:
            raise _ambiguous_judge(names[0])
    elif len(names) == 2:
        if names[0] in _JUDGE_TEXT_PARAMS:
            result = judge(answer.resposta, retrieved)
        elif names[0] in _JUDGE_ANSWER_PARAMS:
            result = judge(answer, retrieved)
        else:
            raise _ambiguous_judge(names[0])
    else:
        raise TypeError(
            f"ambiguous judge signature: expected at most 2 positional arguments, got {len(names)}"
        )
    return _normalize_judge_result(result)


def _ambiguous_judge(first_parameter: str) -> TypeError:
    return TypeError(
        "ambiguous judge signature: first parameter is "
        f"{first_parameter!r}; name it 'answer' to receive the Answer object or "
        "'resposta'/'text'/'claim' to receive the response text"
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


def _normalize_judge_result(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, bool):
        return [] if result else ["unsupported claim"]
    if isinstance(result, str):
        verdict = result.strip().lower()
        if verdict in {"sim", "s", "yes", "true", "ok", "aprovado", "suportado"}:
            return []
        if verdict in {"nao", "não", "no", "false", "rejeitado", "insuficiente"}:
            return ["unsupported claim"]
        return [result] if result.strip() else []
    if isinstance(result, Mapping):
        issues = result.get("issues")
        normalized = [str(item) for item in issues] if isinstance(issues, Sequence) else []
        rejected = any(
            result.get(key) is False for key in ("ok", "supported", "suportado", "aprovado")
        )
        if rejected and not normalized:
            normalized = ["unsupported claim"]
        return normalized
    if isinstance(result, Sequence):
        return [str(item) for item in result if str(item).strip()]
    if getattr(result, "ok", None) is False:
        return ["unsupported claim"]
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


def _same_citation(left: str, right: str) -> bool:
    return _bare_citation(left) == _bare_citation(right)


def _bare_citation(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1].strip()
    return _normalize_space(stripped)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
