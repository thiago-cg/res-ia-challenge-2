import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from src.obs.logging import (
    DEFAULT_LOG_RETENTION_DAYS,
    JsonFormatter,
    bind_request_context,
    configure_logging,
    log_event,
    new_request_id,
    redact_pii,
    request_id_var,
    retention_days,
    session_id_var,
)


@contextmanager
def capture_json_events() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("src.obs")
    old_level = logger.level
    old_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate
        handler.close()


def make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("test.logger", logging.INFO, __file__, 1, message, (), None)


def test_json_formatter_shape_and_context() -> None:
    record = make_record("olá")
    record.event = "unit.event"
    record.status = 200

    with bind_request_context(request_id="rid-1", session_id="sid-1"):
        payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "olá"
    assert payload["request_id"] == "rid-1"
    assert payload["session_id"] == "sid-1"
    assert payload["event"] == "unit.event"
    assert payload["status"] == 200
    assert payload["ts"].endswith("Z")


def test_request_and_session_propagate_to_events() -> None:
    with capture_json_events() as stream:
        with bind_request_context(request_id="req-42", session_id="sess-42"):
            log_event("chat.step", duration_ms=12)

    payload = json.loads(stream.getvalue().strip())

    assert payload["event"] == "chat.step"
    assert payload["request_id"] == "req-42"
    assert payload["session_id"] == "sess-42"
    assert payload["duration_ms"] == 12


def test_bind_request_context_generates_id_and_resets() -> None:
    with bind_request_context() as (request_id, session_id):
        assert request_id == request_id_var.get()
        assert session_id is None
        assert session_id_var.get() is None
        assert len(request_id) == 32
        int(request_id, 16)

    assert request_id_var.get() is None
    assert session_id_var.get() is None


def test_new_request_id_is_opaque_hex() -> None:
    request_id = new_request_id()

    assert len(request_id) == 32
    int(request_id, 16)
    assert request_id != new_request_id()


@pytest.mark.parametrize(
    ("text", "expected", "raw"),
    [
        ("CPF 123.456.789-09", "CPF [CPF]", "123.456.789-09"),
        ("CPF 12345678909", "CPF [CPF]", "12345678909"),
        ("CPF 11122233344", "CPF [CPF]", "11122233344"),
        ("telefone (11) 98765-4321", "telefone [TELEFONE]", "98765-4321"),
        ("telefone 11987654321", "telefone [TELEFONE]", "11987654321"),
        ("email maria.silva@example.com", "email [EMAIL]", "maria.silva@example.com"),
        ("CEP 01310-100", "CEP [CEP]", "01310-100"),
        ("CEP 01310100", "CEP [CEP]", "01310100"),
    ],
)
def test_redact_pii_each_type(text: str, expected: str, raw: str) -> None:
    result = redact_pii(text)

    assert result == expected
    assert raw not in result


def test_redact_pii_keeps_unrelated_text() -> None:
    assert redact_pii("Como pedir medida protetiva?") == "Como pedir medida protetiva?"


def test_question_text_not_logged_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_QUESTION_TEXT", raising=False)
    question = "Meu marido me bateu e meu CPF é 123.456.789-09"

    with capture_json_events() as stream:
        log_event("chat.request", question=question, request_id="rid-question")

    output = stream.getvalue()
    payload = json.loads(output)

    assert "question" not in payload
    assert "Meu marido" not in output
    assert "123.456.789-09" not in output


def test_non_question_fields_still_redact_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_QUESTION_TEXT", raising=False)

    with capture_json_events() as stream:
        log_event("contact", detail="falar com maria@example.com")

    payload = json.loads(stream.getvalue())

    assert payload["detail"] == "falar com [EMAIL]"
    assert "maria@example.com" not in stream.getvalue()


def test_question_text_opt_in_still_redacts_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_QUESTION_TEXT", "true")

    with capture_json_events() as stream:
        log_event("chat.request", question="Meu CPF é 123.456.789-09")

    output = stream.getvalue()
    payload = json.loads(output)

    assert payload["question"] == "Meu CPF é [CPF]"
    assert "123.456.789-09" not in output


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_LOG_RETENTION_DAYS),
        ("0", 0),
        ("3", 3),
        ("-2", 0),
        ("not-a-number", DEFAULT_LOG_RETENTION_DAYS),
    ],
)
def test_retention_days(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int) -> None:
    if raw is None:
        monkeypatch.delenv("LOG_RETENTION_DAYS", raising=False)
    else:
        monkeypatch.setenv("LOG_RETENTION_DAYS", raw)

    assert retention_days() == expected


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    old_level = root.level
    before = {id(handler) for handler in root.handlers}
    try:
        configure_logging("WARNING", json_output=True)
        configure_logging("WARNING", json_output=True)

        ours = [handler for handler in root.handlers if getattr(handler, "_res_ia_obs", False)]
        assert len(ours) == 1
        assert root.level == logging.WARNING
        assert isinstance(ours[0].formatter, JsonFormatter)
    finally:
        for handler in list(root.handlers):
            if id(handler) not in before and getattr(handler, "_res_ia_obs", False):
                root.removeHandler(handler)
                handler.close()
        root.setLevel(old_level)
