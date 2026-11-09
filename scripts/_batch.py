"""Minimal OpenRouter async Batch API client used by the strategy sweep.

OpenRouter exposes an OpenAI-shaped batch endpoint at /api/v1/batches but with
three deviations that matter here:

* the body must carry "endpoint" and "model" *before* "requests" -- the gateway
  parses the body as a stream and rejects the payload otherwise;
* "endpoint" is the path inside the API namespace (/v1/chat/completions), not
  the full /api/v1/... URL;
* the model id keeps its ":batch" suffix, but the batch object reports the
  resolved base model.

Results come back either inline on the batch object ("results") or in an
output file; both shapes are handled.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

CHAT_ENDPOINT = "/v1/chat/completions"

_TERMINAL = {"completed", "failed", "cancelled", "expired"}


class BatchError(RuntimeError):
    """Raised when the batch API refuses a request or ends in a failed state."""


@dataclass
class BatchResult:
    """One completed batch: custom_id -> parsed chat completion payload."""

    batch_id: str
    status: str
    by_id: dict[str, dict[str, Any]]
    errors: dict[str, str]
    usage: dict[str, Any]

    def content(self, custom_id: str) -> str:
        payload = self.by_id.get(custom_id)
        if payload is None:
            return ""
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return ""
        return str(message.get("content") or "")


class OpenRouterBatch:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._key = api_key
        self._base = base_url.rstrip("/")

    def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 120
    ) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": "Bearer " + self._key}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:600]
            except Exception:  # pragma: no cover - best effort diagnostics
                pass
            raise BatchError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise BatchError(f"{method} {path} -> {exc.reason}") from exc
        return json.loads(raw) if raw else {}

    def submit(
        self,
        model: str,
        requests: list[dict[str, Any]],
        *,
        endpoint: str = CHAT_ENDPOINT,
        completion_window: str = "24h",
    ) -> str:
        if not requests:
            raise ValueError("at least one request is required")
        body: dict[str, Any] = {"endpoint": endpoint, "model": model, "requests": requests}
        if completion_window:
            body["completion_window"] = completion_window
        payload = self._call("POST", "/batches", body)
        batch_id = payload.get("id")
        if not batch_id:
            raise BatchError(f"batch create returned no id: {payload}")
        return str(batch_id)

    def wait(
        self,
        batch_id: str,
        *,
        timeout_s: float = 3600,
        poll_s: float = 15,
        source: str | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        while True:
            payload = self._call("GET", "/batches/" + batch_id)
            status = str(payload.get("status"))
            if status in _TERMINAL:
                return payload
            if time.monotonic() - started > timeout_s:
                counts = payload.get("request_counts")
                raise BatchError(
                    f"batch {batch_id} still {status} after {timeout_s:.0f}s ({counts})"
                )
            if source:
                counts = payload.get("request_counts") or {}
                print(
                    "  ["
                    + source
                    + "] "
                    + status
                    + f" {counts.get('completed', 0)}/{counts.get('total', 0)}"
                    + f" ({time.monotonic() - started:.0f}s)",
                    flush=True,
                )
            time.sleep(poll_s)

    def collect(
        self,
        model: str,
        requests: list[dict[str, Any]],
        *,
        endpoint: str = CHAT_ENDPOINT,
        timeout_s: float = 3600,
        poll_s: float = 15,
        label: str = "",
    ) -> BatchResult:
        batch_id = self.submit(model, requests, endpoint=endpoint)
        print(f"  [{label}] submitted {len(requests)} requests -> {batch_id}", flush=True)
        payload = self.wait(batch_id, timeout_s=timeout_s, poll_s=poll_s, source=label)
        return self._parse(batch_id, payload)

    def _parse(self, batch_id: str, payload: dict[str, Any]) -> BatchResult:
        status = str(payload.get("status"))
        results = payload.get("results")
        if results is None and payload.get("output_file_id"):
            results = self._from_file(str(payload["output_file_id"]))
        by_id: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        for item in results or []:
            custom_id = str(item.get("custom_id", ""))
            if item.get("error"):
                errors[custom_id] = json.dumps(item["error"])[:300]
                continue
            response = item.get("response") or {}
            body = response.get("body") if isinstance(response, dict) else None
            if body is None:
                errors[custom_id] = "empty response body"
                continue
            by_id[custom_id] = body
        return BatchResult(
            batch_id=batch_id,
            status=status,
            by_id=by_id,
            errors=errors,
            usage=payload.get("usage") or {},
        )

    def _from_file(self, file_id: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            self._base + "/files/" + file_id + "/content",
            headers={"Authorization": "Bearer " + self._key},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
        items: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if line.strip():
                items.append(json.loads(line))
        return items


def chat_request(
    custom_id: str, model: str, system: str, user: str, *, max_tokens: int = 400
) -> dict[str, Any]:
    """Build one batch entry shaped like a chat completion call."""

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    body: dict[str, Any] = {"model": model, "messages": messages}
    if max_tokens:
        body["max_tokens"] = max_tokens
    return {"custom_id": custom_id, "method": "POST", "url": CHAT_ENDPOINT, "body": body}
