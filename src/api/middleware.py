"""HTTP middleware for request correlation, access logs and security headers."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.obs.logging import (
    bind_request_context,
    log_event,
    new_request_id,
    redact_pii,
)

REQUEST_ID_HEADER = "X-Request-ID"
SESSION_ID_HEADER = "X-Session-ID"


def redact_exception(exc: BaseException) -> str:
    """Return a safe, PII-redacted description of an exception."""
    name = type(exc).__name__
    message = redact_pii(str(exc)).strip()
    return f"{name}: {message}" if message else name


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _is_chat_path(path: str) -> bool:
    return path == "/chat" or path.startswith("/chat/")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request/session context and emit one body-free access event."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = (request.headers.get(REQUEST_ID_HEADER) or "").strip() or new_request_id()
        session_id = (request.headers.get(SESSION_ID_HEADER) or "").strip() or None
        start = time.perf_counter()
        with bind_request_context(request_id=request_id, session_id=session_id):
            try:
                response = await call_next(request)
            except Exception as exc:
                log_event(
                    "http.access",
                    level=logging.ERROR,
                    method=request.method,
                    path=request.url.path,
                    status=500,
                    duration_ms=_elapsed_ms(start),
                    request_id=request_id,
                    error=redact_exception(exc),
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative security headers and forbid caching ``/chat``."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers
        if "x-content-type-options" not in headers:
            headers["X-Content-Type-Options"] = "nosniff"
        if "referrer-policy" not in headers:
            headers["Referrer-Policy"] = "no-referrer"
        if _is_chat_path(request.url.path):
            headers["Cache-Control"] = "no-store"
        return response
