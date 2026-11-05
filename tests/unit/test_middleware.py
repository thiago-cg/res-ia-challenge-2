import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    redact_exception,
)
from src.obs.logging import JsonFormatter


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat")
    def chat(payload: dict[str, str]) -> dict[str, str]:
        return {"answer": "ok", "echo": payload.get("question", "")}

    @app.get("/chat/error")
    def chat_error() -> dict[str, str]:
        raise RuntimeError("falha com CPF 123.456.789-09")

    return app


@contextmanager
def capture_json_events() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("src.obs")
    old_level = logger.level
    old_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate
        handler.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


def test_request_id_header_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "req-echo"})

    assert response.headers["X-Request-ID"] == "req-echo"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)


def test_pii_in_correlation_headers_is_redacted(client: TestClient) -> None:
    with capture_json_events() as stream:
        response = client.get(
            "/health",
            headers={
                "X-Request-ID": "123.456.789-09",
                "X-Session-ID": "maria@example.com",
            },
        )

    payload = json.loads(stream.getvalue().strip())

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "[CPF]"
    assert payload["request_id"] == "[CPF]"
    assert payload["session_id"] == "[EMAIL]"
    assert "123.456.789-09" not in stream.getvalue()
    assert "maria@example.com" not in stream.getvalue()


def test_unsafe_header_generates_a_safe_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "req com espaco"})

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert len(request_id) == 32
    int(request_id, 16)


def test_non_latin1_header_does_not_break_the_response(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": b"req-\xff\xfe"})

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert len(request_id) == 32
    int(request_id, 16)


def test_error_response_keeps_context_and_security_headers(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="src.obs"):
        response = client.get("/chat/error", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-500"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"

    events = [
        record for record in caplog.records if getattr(record, "event", None) == "http.access"
    ]
    assert len(events) == 1
    assert events[0].status == 500
    assert events[0].path == "/chat/error"
    assert events[0].request_id == "req-500"
    assert "123.456.789-09" not in caplog.text


def test_access_log_fields(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="src.obs"):
        response = client.get("/health", headers={"X-Request-ID": "req-access"})

    events = [
        record for record in caplog.records if getattr(record, "event", None) == "http.access"
    ]
    assert len(events) == 1
    event = events[0]
    assert event.method == "GET"
    assert event.path == "/health"
    assert event.status == response.status_code == 200
    assert event.duration_ms >= 0
    assert event.request_id == "req-access"


def test_access_log_has_no_body_or_query(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    question = "Meu CPF é 123.456.789-09 e meu email é maria@example.com"

    with caplog.at_level(logging.INFO, logger="src.obs"):
        response = client.post("/chat", json={"question": question})
        client.get("/health", params={"cpf": "123.456.789-09", "email": "a@b.com"})

    events = [
        record for record in caplog.records if getattr(record, "event", None) == "http.access"
    ]
    rendered = "\n".join(str(value) for record in events for value in vars(record).values())
    assert response.status_code == 200
    assert "Meu CPF" not in rendered
    assert "123.456.789-09" not in rendered
    assert "maria@example.com" not in rendered
    assert "a@b.com" not in rendered
    assert {record.path for record in events} == {"/chat", "/health"}


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Cache-Control" not in response.headers


def test_chat_response_is_not_cacheable(client: TestClient) -> None:
    response = client.post("/chat", json={"question": "Como pedir medida protetiva?"})

    assert response.headers["Cache-Control"] == "no-store"


def test_redact_exception_hides_pii() -> None:
    exc = ValueError(
        "CPF 123.456.789-09, email maria@example.com, telefone (11) 98765-4321, CEP 01310-100"
    )

    text = redact_exception(exc)

    assert text.startswith("ValueError: ")
    assert "[CPF]" in text
    assert "[EMAIL]" in text
    assert "[TELEFONE]" in text
    assert "[CEP]" in text
    for raw in ("123.456.789-09", "maria@example.com", "98765-4321", "01310-100"):
        assert raw not in text
