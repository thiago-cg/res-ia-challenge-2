"""MaxSim reranking over candidate devices (RET-04).

On the target path the rescoring happens inside Qdrant and is injected as a
``rescore`` callable.  On the fallback path an optional pplx 0.6B encoder
reorders the top 50 candidates by late-interaction MaxSim.  Without an encoder
the RRF order is kept untouched so no embedding space is ever mixed.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from src.contracts import RetrievedDevice

DEFAULT_TOP_K = 10
FALLBACK_RERANK_POOL = 50

Rescore = Callable[[str, list[RetrievedDevice]], list[RetrievedDevice]]


class MultiVectorEncoder(Protocol):
    def encode_query(self, text: Any) -> Any: ...

    def encode_document(self, texts: list[str]) -> Any: ...


def maxsim_score(query_vectors: Sequence[Any], doc_vectors: Sequence[Any]) -> float:
    """Sum of the maximum cosine similarity for each query token."""

    query = [_as_vector(vector) for vector in _to_list(query_vectors)]
    doc = [_as_vector(vector) for vector in _to_list(doc_vectors)]
    if not query or not doc:
        return 0.0

    total = 0.0
    for query_vector in query:
        best = max(_cosine(query_vector, doc_vector) for doc_vector in doc)
        total += best
    return total


def rerank(
    pergunta: str,
    candidates: Sequence[RetrievedDevice],
    *,
    encoder: MultiVectorEncoder | None = None,
    top_k: int = DEFAULT_TOP_K,
    rescore: Rescore | None = None,
) -> list[RetrievedDevice]:
    """Return the best ``top_k`` candidates without ever mixing vector spaces.

    ``rescore`` (target path) receives the full candidate pool (at most 150 from
    RET-03).  ``encoder`` (fallback) only sees the first 50 candidates.  With
    neither, candidates are returned in their incoming RRF order.
    """

    if top_k <= 0:
        return []

    pool = list(candidates)
    if rescore is not None:
        rescored = _call_rescore(rescore, pergunta, pool)
        normalized = [item.model_copy(update={"source": "maxsim"}) for item in rescored]
        return _sorted_cap(normalized, top_k)

    if encoder is None:
        return pool[:top_k]

    window = pool[:FALLBACK_RERANK_POOL]
    scored = _score_with_encoder(pergunta, window, encoder)
    return _sorted_cap(scored, top_k)


def _score_with_encoder(
    pergunta: str,
    candidates: Sequence[RetrievedDevice],
    encoder: MultiVectorEncoder,
) -> list[RetrievedDevice]:
    query_vectors = _query_vectors(encoder, pergunta)
    texts = [_document_text(item) for item in candidates]
    doc_vectors = _document_vectors(encoder, texts)

    scored: list[RetrievedDevice] = []
    for item, vectors in zip(candidates, doc_vectors, strict=False):
        score = maxsim_score(query_vectors, vectors)
        scored.append(item.model_copy(update={"score": score, "source": "maxsim"}))
    return scored


def _query_vectors(encoder: MultiVectorEncoder, pergunta: str) -> list[list[float]]:
    try:
        raw = encoder.encode_query([pergunta])
    except (TypeError, AttributeError):
        raw = encoder.encode_query(pergunta)
    return [_as_vector(vector) for vector in _first_matrix(raw)]


def _document_vectors(encoder: MultiVectorEncoder, texts: Sequence[str]) -> list[list[list[float]]]:
    try:
        raw = encoder.encode_document(list(texts))
    except TypeError:
        raw = encoder.encode_document(list(texts), batch_size=8)  # type: ignore[call-arg]
    matrices = _to_list(raw)
    if matrices and _is_vector(matrices[0]):
        matrices = [matrices]
    return [[_as_vector(vector) for vector in matrix] for matrix in matrices]


_QUERY_PARAMS = frozenset({"pergunta", "question", "query", "q", "subquestion", "consulta"})
_CANDIDATE_PARAMS = frozenset(
    {"candidates", "candidatos", "items", "devices", "docs", "cands", "c"}
)
_TOPK_PARAMS = frozenset({"top_k", "k", "limit", "n"})


def _call_rescore(
    rescore: Rescore, pergunta: str, candidates: list[RetrievedDevice]
) -> list[RetrievedDevice]:
    # Inspect once and dispatch by parameter name.  A ``TypeError`` raised inside
    # the callable propagates; ambiguous shapes fail before any call.
    names, varargs = _signature_shape(rescore)
    if names is None:
        raise TypeError(
            "cannot inspect rescore signature; declare it as "
            "rescore(pergunta, candidates) or rescore(pergunta, candidates, top_k)"
        )
    if varargs:
        raise TypeError(
            "ambiguous rescore signature: variadic callables are not supported; "
            "declare rescore(pergunta, candidates) or rescore(pergunta, candidates, top_k)"
        )

    call: Any = rescore
    first = names[0] if names else ""
    if first in _QUERY_PARAMS:
        if len(names) == 1:
            return list(call(pergunta))
        if len(names) == 2 and names[1] in _CANDIDATE_PARAMS:
            return list(call(pergunta, candidates))
        if len(names) == 3 and names[1] in _CANDIDATE_PARAMS and names[2] in _TOPK_PARAMS:
            return list(call(pergunta, candidates, DEFAULT_TOP_K))
        raise _ambiguous_rescore(names)

    if first in _CANDIDATE_PARAMS:
        if len(names) == 1:
            return list(call(candidates))
        second = names[1] if len(names) > 1 else ""
        if len(names) == 2 and second in _TOPK_PARAMS:
            return list(call(candidates, DEFAULT_TOP_K))
        if len(names) == 2 and second in _QUERY_PARAMS:
            return list(call(candidates, pergunta))
        if len(names) == 3 and second in _QUERY_PARAMS and names[2] in _TOPK_PARAMS:
            return list(call(candidates, pergunta, DEFAULT_TOP_K))
        raise _ambiguous_rescore(names)

    if not names:
        return list(call())
    raise _ambiguous_rescore(names)


def _ambiguous_rescore(names: list[str]) -> TypeError:
    return TypeError(
        "ambiguous rescore signature: positional parameters are "
        f"{names!r}; name the first 'pergunta'/'query' or "
        "'candidates'/'items' and the second 'candidates'/'items' or 'top_k'"
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


def _sorted_cap(candidates: list[RetrievedDevice], top_k: int) -> list[RetrievedDevice]:
    return sorted(candidates, key=lambda item: item.score, reverse=True)[:top_k]


def _document_text(item: RetrievedDevice) -> str:
    if item.contexto:
        return f"{item.contexto}\n{item.texto_literal}"
    return item.texto_literal


def _to_list(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def _first_matrix(value: Any) -> list[Any]:
    data = _to_list(value)
    if not data:
        return []
    first = data[0]
    if isinstance(first, (int, float)):
        return [data]
    if _is_vector(first):
        return data
    return _to_list(first)


def _is_vector(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return False
    try:
        data = _to_list(value)
    except TypeError:
        return False
    return bool(data) and isinstance(data[0], (int, float))


def _as_vector(value: Any) -> list[float]:
    return [float(component) for component in _to_list(value)]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
