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
_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
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

_CONTENT_FIELD_NAMES = frozenset(
    {
        "question",
        "question_text",
        "pergunta",
        "pergunta_texto",
        "query",
        "query_text",
        "user_message",
        "user_text",
        "message",
        "body",
        "content",
        "prompt",
        "answer",
        "resposta",
        "resposta_texto",
        "conversation",
        "conversa",
    }
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
    if "." in raw or "-" in raw or _valid_cpf(digits):
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


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, Mapping):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_value(item) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return redact_pii(str(value))


def _safe_extra_key(key: str) -> str:
    if key in _RESERVED_ATTRS or key == "event":
        return f"field_{key}"
    return key


def _sanitize_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    allow_question_text = question_text_enabled()
    for key, value in fields.items():
        name = str(key)
        if name.lower() in _CONTENT_FIELD_NAMES:
            if not allow_question_text:
                continue
            safe[name] = redact_pii(str(value))
            continue
        safe[name] = _redact_value(value)
    return safe


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
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "session_id": getattr(record, "session_id", None) or session_id_var.get(),
            "event": getattr(record, "event", None),
        }
        allow_question_text = question_text_enabled()
        for key, value in vars(record).items():
            if key in _RESERVED_ATTRS or key in payload or key.startswith("_"):
                continue
            if key.lower() in _CONTENT_FIELD_NAMES:
                if not allow_question_text:
                    continue
                payload[key] = redact_pii(str(value))
            else:
                payload[key] = _redact_value(value)
        if record.exc_info:
            payload["exception"] = redact_pii(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable fallback that still redacts PII."""

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            _utc_timestamp(),
            record.levelname,
            record.name,
            f"request_id={request_id_var.get() or '-'}",
            f"session_id={session_id_var.get() or '-'}",
        ]
        event = getattr(record, "event", None)
        if event:
            parts.append(f"event={event}")
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
