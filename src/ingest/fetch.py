from __future__ import annotations

import codecs
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ValidationError

Parser = Literal["planalto", "cnj", "sumulas_pdf"]
Priority = Literal["P0", "P1"]


class SourceManifestError(Exception):
    pass


#: Sent on every download.  planalto.gov.br answers a request that carries the
#: default python-httpx/x.y agent by accepting the connection and then never
#: replying, so the client sees a read timeout instead of an HTTP error
#: (measured 2026-11-16: no UA -> no response in 12 s; any UA -> 200 in 0.4 s).
#: The value keeps the project identifiable instead of impersonating a browser.
USER_AGENT = (
    "Mozilla/5.0 (compatible; ZeliaCorpusIngest/1.0; "
    "+https://github.com/res-ia/zelia) ingestao de fontes legais publicas"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


class FetchError(Exception):
    pass


class Source(BaseModel):
    id: str
    title: str
    url: str
    parser: Parser
    priority: Priority
    tipo: str
    enabled: bool = True
    sha256: str | None = None


class FetchResult(BaseModel):
    source_id: str
    path: Path
    sha256: str
    unchanged: bool
    status_code: int | None


def load_sources(path: str | Path) -> list[Source]:
    manifest_path = Path(path)
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourceManifestError(f"could not read manifest {manifest_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SourceManifestError(f"invalid YAML in {manifest_path}: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise SourceManifestError(f"{manifest_path} must contain a top-level 'sources' list")

    sources: list[Source] = []
    seen: set[str] = set()
    for index, item in enumerate(raw["sources"]):
        if not isinstance(item, dict):
            raise SourceManifestError(f"source at index {index} must be a mapping")
        try:
            source = Source.model_validate(item)
        except ValidationError as exc:
            missing = ", ".join(str(error["loc"][0]) for error in exc.errors())
            raise SourceManifestError(
                f"invalid source at index {index}: missing or invalid field(s): {missing}"
            ) from exc
        if source.id in seen:
            raise SourceManifestError(f"duplicate source id: {source.id}")
        seen.add(source.id)
        sources.append(source)
    return sources


def _raw_filename(source: Source) -> str:
    url_path = urlparse(source.url).path.lower()
    if url_path.endswith(".pdf"):
        return f"{source.id}.pdf"
    if url_path.endswith(".txt"):
        return f"{source.id}.txt"
    return f"{source.id}.html"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sidecar_status(meta_path: Path) -> int | None:
    try:
        payload: Any = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if isinstance(status, int) else None


def _atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_bytes(data)
    temp.replace(path)


_META_CHARSET_RE = re.compile(rb"charset\s*=\s*[\"']?\s*([A-Za-z0-9._:-]+)", re.IGNORECASE)


#: Byte-order marks, longest first so UTF-32 is not mistaken for UTF-16.
#: A BOM outranks any declared charset: planalto.gov.br serves the Lei Maria
#: da Penha page as UTF-16LE with no charset meta, and decoding those bytes as
#: cp1252 yields mojibake that parses to zero articles.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def detect_charset(raw: bytes) -> str:
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return encoding

    match = _META_CHARSET_RE.search(raw[:4096])
    if match:
        declared = match.group(1).decode("ascii", errors="ignore").strip("\"'").lower()
        try:
            codecs.lookup(declared)
        except LookupError:
            pass
        else:
            return declared

    # No BOM and no declaration: a high NUL density means UTF-16 without a BOM.
    head = raw[:200]
    if head and head.count(0) / len(head) > 0.3:
        return "utf-16"

    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8"


def verify_raw_matches_sidecar(source: Source, path: str | Path, dest_dir: str | Path) -> None:
    """Refuse an offline raw file whose bytes no longer match the sidecar.

    ``--offline`` reads whatever sits in ``data/raw``.  A truncated or
    overwritten file produced a parser error ("no article found") that pointed
    at the parser, not at the 3 bytes on disk.  The sidecar records the hash
    of what was downloaded, so a mismatch is detectable before parsing.
    """

    meta_path = Path(dest_dir) / f"{source.id}.meta.json"
    if not meta_path.is_file():
        return
    try:
        meta: Any = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    expected = meta.get("sha256") if isinstance(meta, dict) else None
    if not isinstance(expected, str) or not expected:
        return
    actual = _sha256_file(Path(path))
    if actual == expected:
        return
    raise FetchError(
        f"{source.id}: raw file {Path(path).name} does not match its download "
        f"sidecar (expected sha256 {expected[:12]}..., found {actual[:12]}...); "
        "run --stage download to fetch it again"
    )


def fetch_source(
    source: Source,
    dest_dir: str | Path,
    client: Any | None = None,
    timeout: float = 30,
    retries: int = 3,
    backoff: float = 0.5,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / _raw_filename(source)
    meta_path = dest / f"{source.id}.meta.json"

    if path.is_file():
        digest = _sha256_file(path)
        pinned = source.sha256.lower() if source.sha256 else None
        if pinned is not None:
            if digest == pinned:
                return FetchResult(
                    source_id=source.id,
                    path=path,
                    sha256=digest,
                    unchanged=True,
                    status_code=_sidecar_status(meta_path) or 200,
                )
            # A manifest pin that differs from the local file is authoritative:
            # ignore the sidecar and force a fresh download.

        elif _sidecar_status(meta_path) is not None:
            try:
                meta: Any = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = None
            if isinstance(meta, dict) and meta.get("sha256") == digest:
                return FetchResult(
                    source_id=source.id,
                    path=path,
                    sha256=digest,
                    unchanged=True,
                    status_code=meta.get("status", 200),
                )

    request_headers = {**DEFAULT_HEADERS, **(headers or {})}
    # A blackholed peer answers the TCP handshake and then goes silent, so the
    # read budget is what bounds the call; the connect budget stays short.
    request_timeout = httpx.Timeout(timeout, connect=min(timeout, 15.0))

    owns_client = client is None
    http_client = client if client is not None else httpx.Client(follow_redirects=True)
    last_error: FetchError | None = None
    try:
        for attempt in range(retries + 1):
            try:
                response = http_client.get(
                    source.url, timeout=request_timeout, headers=request_headers
                )
            except httpx.TimeoutException as exc:
                last_error = FetchError(f"{source.id}: timeout after {timeout}s")
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise last_error from exc
            except httpx.TransportError as exc:
                last_error = FetchError(f"{source.id}: transport error: {exc}")
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise last_error from exc

            status_code = int(response.status_code)
            if 500 <= status_code < 600:
                last_error = FetchError(f"{source.id}: HTTP {status_code}")
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise last_error
            if status_code >= 400:
                raise FetchError(f"{source.id}: HTTP {status_code}")

            raw = response.content
            digest = _sha256_bytes(raw)
            _atomic_write(path, raw)
            meta = {
                "source_id": source.id,
                "url": source.url,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "sha256": digest,
                "content_type": response.headers.get("content-type"),
                "status": status_code,
            }
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return FetchResult(
                source_id=source.id,
                path=path,
                sha256=digest,
                unchanged=False,
                status_code=status_code,
            )

        raise last_error or FetchError(f"{source.id}: fetch failed")
    finally:
        if owns_client:
            http_client.close()
