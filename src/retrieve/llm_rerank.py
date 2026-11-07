"""LLM reranking of the candidate pool (RET-04, fallback path).

The dense leg puts the gold device in the top-50 for 85% of the answerable
questions but in the top-10 for only 67%, so the missing recall is an ordering
problem, not a retrieval one.  A small LLM reorders the pool by legal
relevance; on any failure the incoming order is returned unchanged."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from src.contracts import RetrievedDevice

logger = logging.getLogger(__name__)

RERANK_PROMPT_VERSION = "rerank_v1"
DEFAULT_POOL = 30
DEFAULT_MAX_DOC_CHARS = 240

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

SYSTEM_PROMPT = """
Voce e jurista brasileiro especializado em violencia domestica e familiar.
Sua tarefa e ordenar dispositivos legais por relevancia para responder a
pergunta de uma vitima. Responda somente com JSON, sem explicacao.
"""

USER_TEMPLATE = """Pergunta: {pergunta}

Candidatos:
{candidatos}

Ordene os candidatos pela utilidade para responder a pergunta.
Devolva JSON no formato {{"ids": ["id1", "id2", ...]}} com no maximo
{top_k} ids, do mais relevante para o menos relevante.
Use somente ids da lista de candidatos.
"""


class LLMReranker:
    """Reorder a candidate pool with an LLM, keeping the order on failure."""

    def __init__(
        self,
        llm: Any,
        *,
        pool: int = DEFAULT_POOL,
        max_doc_chars: int = DEFAULT_MAX_DOC_CHARS,
        timeout: float = 45.0,
    ) -> None:
        if pool <= 0:
            raise ValueError("pool must be positive")
        self._llm = llm
        self.pool = pool
        self.max_doc_chars = max_doc_chars
        self.timeout = timeout

    def __call__(
        self,
        pergunta: str,
        candidates: Sequence[RetrievedDevice],
        top_k: int = 10,
    ) -> list[RetrievedDevice]:
        pool = list(candidates)
        if len(pool) <= 1:
            return pool

        window = pool[: self.pool]
        prompt = USER_TEMPLATE.format(
            pergunta=pergunta.strip(),
            candidatos=self._format(window),
            top_k=max(1, min(top_k, len(window))),
        )
        try:
            raw = self._llm.complete(SYSTEM_PROMPT, prompt, timeout=self.timeout)
        except Exception as exc:
            logger.warning("rerank_failed error=%s", type(exc).__name__)
            return pool

        ordered = self._parse(raw, window)
        if not ordered:
            return pool

        chosen = {item.device_id for item in ordered}
        rest = [item for item in pool if item.device_id not in chosen]
        ranked = ordered + rest
        total = len(ranked)
        return [
            item.model_copy(update={"score": float(total - index), "source": "llm-rerank"})
            for index, item in enumerate(ranked)
        ]

    def _format(self, candidates: Sequence[RetrievedDevice]) -> str:
        lines = []
        for index, item in enumerate(candidates, start=1):
            text = (item.texto_literal or "").strip().replace("\n", " ")
            if len(text) > self.max_doc_chars:
                text = text[: self.max_doc_chars].rstrip() + "..."
            citacao = item.citacao.strip() or item.device_id
            lines.append(f"{index}. id={item.device_id} | {citacao} | {text}")
        return "\n".join(lines)

    def _parse(self, raw: str, window: Sequence[RetrievedDevice]) -> list[RetrievedDevice]:
        allowed = {item.device_id: item for item in window}
        ids = _extract_ids(raw)
        ordered: list[RetrievedDevice] = []
        seen: set[str] = set()
        for device_id in ids:
            if device_id in allowed and device_id not in seen:
                seen.add(device_id)
                ordered.append(allowed[device_id])
        return ordered


def _extract_ids(raw: str) -> list[str]:
    """Pull the ordered id list out of a JSON (or almost-JSON) response."""

    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = payload.get("ids") or payload.get("order") or []
    if not isinstance(payload, list):
        return []
    ids: list[str] = []
    for item in payload:
        if isinstance(item, str):
            ids.append(item.strip())
        elif isinstance(item, dict):
            value = item.get("id") or item.get("device_id")
            if isinstance(value, str):
                ids.append(value.strip())
    return ids


class LazyLLM:
    """Build the LLM client on first use so startup never needs a provider."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._client: Any = None

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        if self._client is None:
            from src.generate.llm import get_llm

            self._client = get_llm(self._settings)
        return str(self._client.complete(system, user, timeout=timeout))
