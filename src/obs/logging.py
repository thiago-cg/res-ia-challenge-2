"""Structured, privacy-aware logging for the legal RAG service.

Logs must identify a request through ``request_id``/``session_id`` instead of
user text. Question text is dropped unless ``LOG_QUESTION_TEXT=true`` and, even
then, PII is redacted. ``LOG_RETENTION_DAYS`` defaults to 7; ``0`` means no
persistence. Any file or database sink must honor :func:`retention_days`; this
module only writes to stderr and never writes question text on its own.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

DEFAULT_LOG_RETENTION_DAYS = 7
LOG_QUESTION_TEXT_ENV = "LOG_QUESTION_TEXT"
LOG_RETENTION_DAYS_ENV = "LOG_RETENTION_DAYS"
SERVICE_LOGGER_NAME = "src.obs"

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id", default=None
)

_LOGGER = logging.getLogger(SERVICE_LOGGER_NAME)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CPF_RE = re.compile(r"(?<!\d)\d{3}[ .-]?\d{3}[ .-]?\d{3}[ .-]?\d{2}(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)\(?\d{2}\)?\s?9?\d{4}-?\d{4}(?!\d)")
_CEP_RE = re.compile(r"(?<!\d)\d{5}-?\d{3}(?!\d)")

_RESERVED_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)

_DROP = object()

_CONTENT_KEY_NAMES = frozenset(
    {
        "question",
        "questiontext",
        "userquestion",
        "pergunta",
        "perguntatexto",
        "query",
        "querytext",
        "message",
        "messagebody",
        "msg",
        "text",
        "input",
        "inputtext",
        "userinput",
        "utterance",
        "userutterance",
        "payload",
        "content",
        "body",
        "raw",
        "rawtext",
        "prompt",
        "systemprompt",
        "userprompt",
        "answer",
        "output",
        "resposta",
        "respostatexto",
        "conversation",
        "conversa",
        "history",
        "chatmessage",
        "transcript",
    }
)

_PII_KEY_NAMES = frozenset(
    {
        "cpf",
        "cpfnumber",
        "phone",
        "phonenumber",
        "telefone",
        "telefonenumber",
        "celular",
        "mobile",
        "email",
        "mail",
        "cep",
        "postalcode",
        "address",
        "endereco",
    }
)

_SAFE_FIELD_NAMES = frozenset(
    {
        "request_id",
        "session_id",
        "method",
        "path",
        "status",
        "status_code",
        "duration_ms",
        "elapsed_ms",
        "latency_ms",
        "error",
        "error_type",
        "source",
        "sources",
        "stage",
        "step",
        "model",
        "model_name",
        "prompt_version",
        "retrieval_path",
        "embedding_provider",
        "risk_level",
        "risk_classification",
        "risk_kind",
        "immediate",
        "signals",
        "subquestions",
        "retrieved_ids",
        "used_ids",
        "citation_ids",
        "doc_ids",
        "ids",
        "scores",
        "rerank_scores",
        "search_scores",
        "base_updated_at",
        "index_version",
        "verifier_result",
        "passed",
        "abstained",
        "abstencao",
        "motivo_abstencao",
        "count",
        "total",
        "offset",
        "limit",
        "cache_hit",
        "cached_tokens",
        "tokens",
        "token_count",
        "retry",
        "attempt",
        "found",
        "reason",
        "version",
        "duration",
        "n",
        "size",
        "bytes",
    }
)

_SAFE_FIELD_SUFFIXES = (
    "_id",
    "_ids",
    "_ms",
    "_count",
    "_score",
    "_scores",
    "_version",
    "_at",
    "_length",
    "_tokens",
    "_model",
    "_provider",
    "_status",
)

_MANAGED_FIELDS = frozenset(
    {"ts", "level", "logger", "message", "request_id", "session_id", "event"}
)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def new_request_id() -> str:
    """Return an opaque request identifier without PII."""
    return uuid.uuid4().hex


def question_text_enabled() -> bool:
    """Whether opt-in question text logging is enabled (default: false)."""
    return os.getenv(LOG_QUESTION_TEXT_ENV, "false").strip().lower() in _TRUTHY


def retention_days() -> int:
    """Return the log retention window from ``LOG_RETENTION_DAYS``.

    Defaults to 7 days. ``0`` means no persistence; invalid values fall back to
    the default and negative values are clamped to zero.
    """
    raw = os.getenv(LOG_RETENTION_DAYS_ENV, str(DEFAULT_LOG_RETENTION_DAYS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LOG_RETENTION_DAYS
    return max(value, 0)


def _valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for index in (9, 10):
        total = sum(
            int(digit) * (index + 1 - position) for position, digit in enumerate(digits[:index])
        )
        check = (total * 10) % 11
        if check == 10:
            check = 0
        if check != int(digits[index]):
            return False
    return True


def _looks_like_mobile(digits: str) -> bool:
    if len(digits) != 11:
        return False
    area_code = int(digits[:2])
    return 11 <= area_code <= 99 and digits[2] == "9"


def _replace_cpf(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if any(separator in raw for separator in " .-") or _valid_cpf(digits):
        return "[CPF]"
    if _looks_like_mobile(digits):
        return raw
    return "[CPF]"


def redact_pii(text: str) -> str:
    """Redact CPF, phone, e-mail and CEP from ``text``."""
    if not text:
        return text
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _CPF_RE.sub(_replace_cpf, text)
    text = _PHONE_RE.sub("[TELEFONE]", text)
    text = _CEP_RE.sub("[CEP]", text)
    return text


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_safe_field_name(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered in _SAFE_FIELD_NAMES or lowered.endswith(_SAFE_FIELD_SUFFIXES)


def _redact_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return redact_pii(str(value))


def _sanitize_value(value: Any, allow_question_text: bool) -> Any:
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, allow_question_text)
    if isinstance(value, (list, tuple, set, frozenset)):
        items: list[Any] = []
        for item in value:
            sanitized = _sanitize_value(item, allow_question_text)
            if sanitized is not _DROP:
                items.append(sanitized)
        return items
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return redact_pii(str(value))


def _sanitize_mapping(mapping: Mapping[Any, Any], allow_question_text: bool) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in mapping.items():
        name = str(key)
        normalized = _normalize_key(name)
        if normalized in _PII_KEY_NAMES:
            nested = _sanitize_value(value, allow_question_text)
            if nested is not _DROP:
                sanitized[name] = redact_pii(str(nested))
        elif normalized in _CONTENT_KEY_NAMES:
            if allow_question_text:
                sanitized[name] = redact_pii(str(value))
        else:
            nested = _sanitize_value(value, allow_question_text)
            if nested is not _DROP:
                sanitized[name] = nested
    return sanitized


def _sanitize_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    allow_question_text = question_text_enabled()
    sanitized: dict[str, Any] = {}
    for key, value in fields.items():
        name = str(key)
        normalized = _normalize_key(name)
        if normalized in _PII_KEY_NAMES:
            nested = _sanitize_value(value, allow_question_text)
            if nested is not _DROP:
                sanitized[name] = redact_pii(str(nested))
            continue
        if normalized in _CONTENT_KEY_NAMES:
            if allow_question_text:
                sanitized[name] = redact_pii(str(value))
            continue
        if not _is_safe_field_name(name):
            continue
        nested = _sanitize_value(value, allow_question_text)
        if nested is not _DROP:
            sanitized[name] = nested
    return sanitized


def _safe_extra_key(key: str) -> str:
    if key in _RESERVED_ATTRS or key == "event":
        return f"field_{key}"
    return key


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    fields = {
        key: value
        for key, value in vars(record).items()
        if key not in _RESERVED_ATTRS and key not in _MANAGED_FIELDS and not key.startswith("_")
    }
    return _sanitize_fields(fields)


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Log one structured event, redacting PII and dropping user content.

    Question/answer/body fields are omitted unless ``LOG_QUESTION_TEXT=true``;
    when enabled they are still passed through :func:`redact_pii`.
    """
    safe = _sanitize_fields(fields)
    extra: dict[str, Any] = {"event": event}
    for key, value in safe.items():
        extra[_safe_extra_key(key)] = value
    _LOGGER.log(level, event, extra=extra)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record with request/session context."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_pii(record.getMessage()),
            "request_id": _redact_optional_text(
                getattr(record, "request_id", None) or request_id_var.get()
            ),
            "session_id": _redact_optional_text(
                getattr(record, "session_id", None) or session_id_var.get()
            ),
            "event": _redact_optional_text(getattr(record, "event", None)),
        }
        payload.update(_record_extras(record))
        if record.exc_info:
            payload["exception"] = redact_pii(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def _render_extra_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        rendered = str(value)
    else:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered.replace("\r", " ").replace("\n", " ").replace("\t", " ")


class TextFormatter(logging.Formatter):
    """Human-readable fallback that still redacts PII and keeps safe extras."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = _redact_optional_text(request_id_var.get()) or "-"
        session_id = _redact_optional_text(session_id_var.get()) or "-"
        parts = [
            _utc_timestamp(),
            record.levelname,
            record.name,
            f"request_id={request_id}",
            f"session_id={session_id}",
        ]
        event = _redact_optional_text(getattr(record, "event", None))
        if event:
            parts.append(f"event={event}")
        for key, value in _record_extras(record).items():
            parts.append(f"{key}={_render_extra_value(value)}")
        line = " ".join(parts) + " " + redact_pii(record.getMessage())
        if record.exc_info:
            line += "\n" + redact_pii(self.formatException(record.exc_info))
        return line


def _coerce_level(level: str) -> int:
    resolved = logging.getLevelNamesMapping().get(str(level).upper())
    return resolved if resolved is not None else logging.INFO


class _ServiceHandler(logging.StreamHandler):
    """Stderr handler tagged so reconfigure replaces only our own handler."""

    _res_ia_obs = True


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure one stderr handler on the root logger.

    Idempotent: repeated calls replace the handler installed by this module
    instead of stacking handlers.
    """
    root = logging.getLogger()
    root.setLevel(_coerce_level(level))
    for handler in list(root.handlers):
        if getattr(handler, "_res_ia_obs", False):
            root.removeHandler(handler)
            handler.close()
    handler = _ServiceHandler()
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())
    root.addHandler(handler)


@contextmanager
def bind_request_context(
    request_id: str | None = None, session_id: str | None = None
) -> Iterator[tuple[str, str | None]]:
    """Bind request/session IDs to the current context for downstream logs."""
    bound_request_id = request_id or new_request_id()
    request_token = request_id_var.set(bound_request_id)
    session_token = session_id_var.set(session_id)
    try:
        yield bound_request_id, session_id
    finally:
        session_id_var.reset(session_token)
        request_id_var.reset(request_token)
