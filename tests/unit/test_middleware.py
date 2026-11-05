import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    redact_exception,
)


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

    return app


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
