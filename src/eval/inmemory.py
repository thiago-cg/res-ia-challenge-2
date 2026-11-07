"""In-memory evaluation adapters for the OpenRouter benchmark (EVA-03).

The production fallback path needs Postgres/pgvector and, for the target path,
Qdrant.  This module keeps the *same* ``LegalRAGPipeline`` orchestration while
replacing only the storage and search adapters:

- ``InMemoryRepo`` mirrors the exact ``(device_id, norm_version_id)`` hydration
  contract and the ``vigencia`` window used by ``PostgresRepo``;
- ``NumpyDenseSearcher`` computes cosine similarity over cached vectors;
- ``BM25FtsSearcher`` is a small lexical stand-in for Postgres FTS.

It is a benchmark harness, not a production fallback: vectors are held in
memory and the BM25 tokenizer is not the Postgres Portuguese configuration.
The report must say so.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from src.api.main import LegalRAGPipeline, PipelineResult
from src.contracts import RetrievedDevice
from src.generate.fallback import abstain as fallback_abstain
from src.generate.llm import LLMClient
from src.retrieve.hydrate import hydrate
from src.retrieve.query import default_facts
from src.safety.risk import classify_risk, emergency_answer

CorpusRow = dict[str, Any]
PairKey = tuple[str, int]

_CURRENT_STATUS = frozenset({"vigente", "alterado"})
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "ao",
        "aos",
        "as",
        "com",
        "como",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "entre",
        "era",
        "essa",
        "esse",
        "esta",
        "este",
        "eu",
        "foi",
        "ha",
        "isso",
        "ja",
        "mais",
        "mas",
        "me",
        "mesmo",
        "meu",
        "minha",
        "muito",
        "na",
        "nao",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "ou",
        "para",
        "pela",
        "pelo",
        "por",
        "que",
        "se",
        "sem",
        "ser",
        "seu",
        "sua",
        "suas",
        "seus",
        "tem",
        "um",
        "uma",
    }
)


def load_corpus(paths: Sequence[str | Path]) -> list[CorpusRow]:
    """Load one or more JSONL corpora, rejecting rows without identity."""

    rows: list[CorpusRow] = []
    for path in paths:
        for line_number, line in enumerate(
            Path(path).read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            if not payload.get("device_id") or payload.get("norm_version_id") is None:
                raise ValueError(f"{path}:{line_number}: missing device_id/norm_version_id")
            rows.append(payload)
    return rows


def dedupe_corpus_rows(rows: Sequence[CorpusRow]) -> list[CorpusRow]:
    """Keep one row per pair, preferring the latest vigência and the longest text."""

    best: dict[PairKey, CorpusRow] = {}
    for row in rows:
        if not str(row.get("texto_literal") or "").strip():
            continue
        key = (str(row["device_id"]), int(row["norm_version_id"]))
        current = best.get(key)
        if current is None or _version_key(row) > _version_key(current):
            best[key] = row
        elif _version_key(row) == _version_key(current) and len(
            str(row.get("texto_literal") or "")
        ) > len(str(current.get("texto_literal") or "")):
            best[key] = row
    return list(best.values())


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _version_key(row: Mapping[str, Any]) -> tuple[date, int]:
    inicio = _as_date(row.get("vigencia_inicio")) or date.min
    return inicio, int(row.get("norm_version_id") or 0)


def _in_force(row: Mapping[str, Any], on_date: date) -> bool:
    """Date window only; mirrors dated ``dense_search``/``fts_search`` SQL."""
    inicio = _as_date(row.get("vigencia_inicio"))
    fim = _as_date(row.get("vigencia_fim"))
    if inicio is not None and inicio > on_date:
        return False
    if fim is not None and fim < on_date:
        return False
    return True


def _is_current(row: Mapping[str, Any], on_date: date) -> bool:
    """Current-version predicate; mirrors ``get_current_version_id`` SQL."""
    if str(row.get("vigencia_status") or "") not in _CURRENT_STATUS:
        return False
    return _in_force(row, on_date)


def _matching_row(
    rows: Sequence[CorpusRow],
    on_date: date,
    predicate: Any,
) -> CorpusRow | None:
    matches = [row for row in rows if predicate(row, on_date)]
    if not matches:
        return None
    return max(matches, key=_version_key)


class InMemoryRepo:
    """Minimal repo with the same hydration and version contract as Postgres."""

    def __init__(self, rows: Sequence[CorpusRow]) -> None:
        self.rows = list(rows)
        self._by_pair: dict[PairKey, CorpusRow] = {}
        self._by_device: dict[str, list[CorpusRow]] = defaultdict(list)
        self._by_article: dict[PairKey, CorpusRow] = {}
        for row in self.rows:
            pair = (str(row["device_id"]), int(row["norm_version_id"]))
            self._by_pair.setdefault(pair, row)
            self._by_device[pair[0]].append(row)
            artigo = str(row.get("artigo_id") or pair[0])
            self._by_article.setdefault((artigo, pair[1]), row)

    def get_device_version(self, device_id: str, norm_version_id: int) -> CorpusRow | None:
        return self._by_pair.get((device_id, int(norm_version_id)))

    def get_device_version_on(self, device_id: str, on_date: date) -> CorpusRow | None:
        return _matching_row(self._by_device.get(device_id, []), on_date, _in_force)

    def get_current_version_id(self, device_id: str, data_fato: date | None = None) -> int | None:
        row = _matching_row(
            self._by_device.get(device_id, []),
            data_fato or date.today(),
            _is_current,
        )
        return int(row["norm_version_id"]) if row is not None else None

    def find(self, norm_id: str, artigo_id: str) -> CorpusRow | None:
        for row in self._by_device.get(artigo_id, []):
            if str(row.get("norm_id")) == norm_id:
                return row
        for row in self.rows:
            if str(row.get("norm_id")) == norm_id and str(row.get("artigo_id")) == artigo_id:
                return row
        return None

    def lookup(self, artigo_id: str, norm_version_id: int) -> CorpusRow | None:
        row = self._by_article.get((artigo_id, int(norm_version_id)))
        if row is not None:
            return row
        return self._by_pair.get((artigo_id, int(norm_version_id)))

    def get_data_atualizacao_base(self) -> str | None:
        return None

    def health_snapshot(self) -> tuple[str, str | None, str | None]:
        versions = [int(row["norm_version_id"]) for row in self.rows]
        return "ok", (str(max(versions)) if versions else None), None


class NumpyDenseSearcher:
    """Cosine search over a fixed matrix of cached embeddings."""

    def __init__(
        self,
        rows: Sequence[CorpusRow],
        vectors: Mapping[PairKey, Sequence[float]],
        encoder: Any,
        *,
        dimension: int | None = None,
    ) -> None:
        self.encoder = encoder
        self.rows: list[CorpusRow] = []
        matrix: list[Sequence[float]] = []
        for row in rows:
            pair = (str(row["device_id"]), int(row["norm_version_id"]))
            vector = vectors.get(pair)
            if vector is None:
                continue
            self.rows.append(row)
            matrix.append(vector)
        if not self.rows:
            self.matrix = np.empty((0, dimension or 0), dtype=np.float32)
        else:
            self.matrix = np.asarray(matrix, dtype=np.float32)
        norms = np.linalg.norm(self.matrix, axis=1) if self.matrix.size else np.empty(0)
        norms[norms == 0.0] = 1.0
        if self.matrix.size:
            self.matrix = self.matrix / norms[:, None]

    def search(
        self, query: str, limit: int, data_fato: date | None = None
    ) -> list[RetrievedDevice]:
        if limit <= 0 or not self.rows:
            return []
        raw = self.encoder.encode_query(query)
        if raw and isinstance(raw[0], (list, tuple)):
            raw = raw[0]
        query_vector = np.asarray(raw, dtype=np.float32)
        norm = float(np.linalg.norm(query_vector))
        if norm == 0.0:
            return []
        query_vector = query_vector / norm
        if query_vector.shape[0] != self.matrix.shape[1]:
            raise ValueError(
                f"query vector has {query_vector.shape[0]} dimensions, "
                f"index has {self.matrix.shape[1]}"
            )
        scores = self.matrix @ query_vector
        on_date = data_fato or date.today()
        keep = _in_force if data_fato is not None else _is_current
        order = np.argsort(-scores)
        hits: list[RetrievedDevice] = []
        for index in order:
            row = self.rows[int(index)]
            if not keep(row, on_date):
                continue
            hits.append(_as_retrieved(row, float(scores[int(index)]), "dense"))
            if len(hits) >= limit:
                break
        return hits


class BM25FtsSearcher:
    """Okapi BM25 over ``search_text`` as a lexical stand-in for Postgres FTS."""

    def __init__(
        self,
        rows: Sequence[CorpusRow],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.rows = list(rows)
        self.k1 = k1
        self.b = b
        self._tokens: list[list[str]] = []
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, row in enumerate(self.rows):
            tokens = _tokenize(str(row.get("search_text") or row.get("texto_literal") or ""))
            self._tokens.append(tokens)
            counts: dict[str, int] = defaultdict(int)
            for token in tokens:
                counts[token] += 1
            for token, count in counts.items():
                self._postings[token].append((index, count))
        self._avgdl = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens) if self._tokens else 0.0
        )

    def search(
        self, query: str, limit: int, data_fato: date | None = None
    ) -> list[RetrievedDevice]:
        if limit <= 0 or not self.rows:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        on_date = data_fato or date.today()
        scores: dict[int, float] = defaultdict(float)
        total = len(self.rows)
        for token in query_tokens:
            postings = self._postings.get(token, ())
            if not postings:
                continue
            idf = math.log(1.0 + (total - len(postings) + 0.5) / (len(postings) + 0.5))
            for index, frequency in postings:
                doc_len = len(self._tokens[index])
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * doc_len / (self._avgdl or 1.0)
                )
                scores[index] += idf * frequency * (self.k1 + 1.0) / denominator
        ranked = sorted(
            scores.items(), key=lambda item: (-item[1], self.rows[item[0]]["device_id"])
        )
        keep = _in_force if data_fato is not None else _is_current
        hits: list[RetrievedDevice] = []
        for index, score in ranked:
            row = self.rows[index]
            if not keep(row, on_date):
                continue
            hits.append(_as_retrieved(row, score, "bm25"))
            if len(hits) >= limit:
                break
        return hits


class EmptyFtsSearcher:
    """Dense-only scenario: no lexical list, so RRF keeps the dense order."""

    def search(self, query: str, limit: int, data_fato: date | None = None) -> list[Any]:
        return []


def build_benchmark_pipeline(
    *,
    rows: Sequence[CorpusRow],
    vectors: Mapping[PairKey, Sequence[float]],
    encoder: Any,
    settings: Any,
    llm: LLMClient | None = None,
    mode: str = "hybrid",
) -> LegalRAGPipeline:
    """Build the real pipeline with in-memory storage and the chosen retrieval mode."""

    repo = InMemoryRepo(rows)
    dense = NumpyDenseSearcher(rows, vectors, encoder)
    if mode == "dense":
        fts: Any = EmptyFtsSearcher()
    elif mode == "hybrid":
        fts = BM25FtsSearcher(rows)
    else:
        raise ValueError(f"unknown benchmark mode: {mode!r}")
    return LegalRAGPipeline(
        repo=repo,
        settings=settings,
        llm=llm,
        dense=dense,
        fts=fts,
        encoder=encoder,
    )


class GoldContextPipeline:
    """Generation scenario: skip retrieval and hydrate the gold devices."""

    def __init__(
        self,
        *,
        repo: InMemoryRepo,
        settings: Any,
        llm: LLMClient,
        gold_by_question: Mapping[str, Sequence[str]],
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.llm = llm
        self.gold_by_question = dict(gold_by_question)
        self._pipeline = LegalRAGPipeline(repo=repo, settings=settings, llm=llm)

    def answer(self, message: str, facts: Any = None) -> PipelineResult:
        if classify_risk(message).immediate:
            return PipelineResult(emergency_answer(), True, None)

        gold = self.gold_by_question.get(message, ())
        if not gold:
            return PipelineResult(fallback_abstain("fora_do_corpus"), False, None)

        pairs: list[PairKey] = []
        for device_id in gold:
            version = self.repo.get_current_version_id(
                device_id, facts.data_fato if facts is not None else None
            )
            if version is not None:
                pairs.append((device_id, version))
        if not pairs:
            return PipelineResult(fallback_abstain("contexto_incompleto"), False, None)

        devices = hydrate(pairs, repo=self.repo).devices
        if not devices:
            return PipelineResult(fallback_abstain("contexto_incompleto"), False, None)
        expanded = self._pipeline._expand(devices)
        return self._pipeline._generate(
            message,
            facts or default_facts(),
            [message],
            expanded,
        )


def _tokenize(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in decomposed if not unicodedata.combining(char))
    return [
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in _STOPWORDS
    ]


def _as_retrieved(row: Mapping[str, Any], score: float, source: str) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=str(row["device_id"]),
        norm_version_id=int(row["norm_version_id"]),
        score=float(score),
        source=source,  # type: ignore[arg-type]
        texto_literal=str(row.get("texto_literal") or ""),
        citacao=str(row.get("citacao") or ""),
        vigencia=row.get("vigencia_status"),
        contexto=row.get("contexto"),
        explicacao=row.get("explicacao"),
        fonte_url=row.get("fonte_url"),
    )
