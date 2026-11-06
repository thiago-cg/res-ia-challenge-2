from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.main import PipelineResult, create_app, health_status
from src.config import Settings
from src.contracts import Answer


class NullRepo:
    def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None:
        return None

    def get_device_version_on(self, device_id: str, on_date: date) -> Any | None:
        return None


class StaticProbe:
    def snapshot(self) -> dict[str, Any]:
        return health_status(
            database="ok",
            qdrant="ok",
            data_atualizacao_base="2026-11-05",
        )


class StubPipeline:
    def answer(self, message: str, facts: Any = None) -> PipelineResult:
        return PipelineResult(_answer(), False, "2026-11-05")


class ExplodingPipeline:
    def answer(self, message: str, facts: Any = None) -> PipelineResult:
        raise RuntimeError("boom")


def _answer() -> Answer:
    return Answer(
        resposta="Resposta de teste.",
        citacoes=[],
        proximos_passos=[],
        encaminhamentos=[],
        premissas=[],
        nivel_confianca="medio",
        abstencao=False,
        motivo_abstencao=None,
    )


def build_app(*, log_level: str = "WARNING", pipeline: Any = None) -> FastAPI:
    return create_app(
        settings=Settings(log_level=log_level),
        pipeline=pipeline or StubPipeline(),
        source_repo=NullRepo(),
        health_probe=StaticProbe(),
        data_atualizacao_base="2026-11-05",
    )


def test_health_exposes_request_id_and_security_headers() -> None:
    client = TestClient(build_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_chat_response_is_not_cacheable() -> None:
    client = TestClient(build_app())

    response = client.post(
        "/chat",
        json={"session_id": "session-1", "message": "Ele está me batendo agora."},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_unhandled_exception_returns_safe_500() -> None:
    secret = "falha interna com CPF 123.456.789-09"
    app = build_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(secret)

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom", headers={"X-Request-ID": "req-boom"})

    assert response.status_code == 500
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.json() == {"detail": "Internal Server Error"}
    assert response.headers["X-Request-ID"] == "req-boom"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "123.456.789-09" not in response.text
    assert "RuntimeError" not in response.text


def test_chat_logs_reuse_client_request_id(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(build_app())

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/chat",
            json={"session_id": "session-1", "message": "Ele está me batendo agora."},
            headers={"X-Request-ID": "abc123"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "abc123"

    chat_events = [
        record
        for record in caplog.records
        if record.getMessage().startswith(("chat_request", "chat_response"))
    ]
    assert len(chat_events) == 2
    assert all("request_id=abc123" in record.getMessage() for record in chat_events)
    minted = [
        match
        for record in chat_events
        for match in re.findall(r"request_id=([0-9a-f]{32})", record.getMessage())
    ]
    assert minted == []

    access_events = [
        record for record in caplog.records if getattr(record, "event", None) == "http.access"
    ]
    assert access_events
    assert all(event.request_id == "abc123" for event in access_events)


def test_chat_failure_log_reuses_client_request_id(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(build_app(pipeline=ExplodingPipeline()))

    with caplog.at_level(logging.INFO, logger="src.api.main"):
        response = client.post(
            "/chat",
            json={"session_id": "session-1", "message": "Como pedir medida protetiva?"},
            headers={"X-Request-ID": "abc123"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "abc123"
    failures = [
        record for record in caplog.records if record.getMessage().startswith("chat_failure")
    ]
    assert len(failures) == 1
    assert "request_id=abc123" in failures[0].getMessage()


def test_repeated_create_app_keeps_one_logging_handler() -> None:
    root = logging.getLogger()
    old_level = root.level
    try:
        build_app(log_level="WARNING")
        build_app(log_level="WARNING")

        ours = [handler for handler in root.handlers if getattr(handler, "_res_ia_obs", False)]
        assert len(ours) == 1
        assert root.level == logging.WARNING
    finally:
        root.setLevel(old_level)
