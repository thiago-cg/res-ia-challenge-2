"""HTTP middleware for request correlation, access logs and security headers."""

from __future__ import annotations

import logging
import re
import time

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.obs.logging import (
    SERVICE_LOGGER_NAME,
    bind_request_context,
    log_event,
    new_request_id,
    redact_pii,
)

REQUEST_ID_HEADER = "X-Request-ID"
SESSION_ID_HEADER = "X-Session-ID"

_LOGGER = logging.getLogger(SERVICE_LOGGER_NAME)

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,128}$")


def redact_exception(exc: BaseException) -> str:
    """Return a safe, PII-redacted description of an exception."""
    name = type(exc).__name__
    message = redact_pii(str(exc)).strip()
    return f"{name}: {message}" if message else name


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _is_chat_path(path: str) -> bool:
    return path == "/chat" or path.startswith("/chat/")


def _sanitize_header_identifier(value: str | None) -> str | None:
    """Return a safe correlation ID or ``None`` when the header is unusable."""
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or not candidate.isascii():
        return None
    redacted = redact_pii(candidate)
    if len(redacted) > 128 or not _SAFE_IDENTIFIER_RE.fullmatch(redacted):
        return None
    return redacted


def _apply_security_headers(response: Response, path: str) -> None:
    headers = response.headers
    if "x-content-type-options" not in headers:
        headers["X-Content-Type-Options"] = "nosniff"
    if "referrer-policy" not in headers:
        headers["Referrer-Policy"] = "no-referrer"
    if _is_chat_path(path):
        headers["Cache-Control"] = "no-store"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request/session context and emit one body-free access event."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = (
            _sanitize_header_identifier(request.headers.get(REQUEST_ID_HEADER)) or new_request_id()
        )
        session_id = _sanitize_header_identifier(request.headers.get(SESSION_ID_HEADER))
        request.state.request_id = request_id
        request.state.session_id = session_id
        start = time.perf_counter()
        with bind_request_context(request_id=request_id, session_id=session_id):
            try:
                response = await call_next(request)
            except Exception as exc:
                _LOGGER.exception(
                    "http.access: %s",
                    redact_exception(exc),
                    extra={
                        "event": "http.access",
                        "method": request.method,
                        "path": request.url.path,
                        "status": 500,
                        "duration_ms": _elapsed_ms(start),
                        "request_id": request_id,
                    },
                )
                raise
            response.headers[REQUEST_ID_HEADER] = request_id
            log_event(
                "http.access",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=_elapsed_ms(start),
                request_id=request_id,
            )
            return response


def install_error_handlers(app: FastAPI) -> None:
    """Register a safe 500 handler that preserves correlation/security headers."""

    async def internal_error_handler(request: Request, _exc: Exception) -> Response:
        stored_id = getattr(request.state, "request_id", None)
        request_id = (
            _sanitize_header_identifier(str(stored_id)) if stored_id is not None else None
        ) or new_request_id()
        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)
        response.headers[REQUEST_ID_HEADER] = request_id
        _apply_security_headers(response, request.url.path)
        return response

    app.add_exception_handler(Exception, internal_error_handler)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative security headers and forbid caching ``/chat``."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        _apply_security_headers(response, request.url.path)
        return response
