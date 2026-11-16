from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.ingest import run as run_module
from src.ingest.fetch import (
    USER_AGENT,
    FetchError,
    Source,
    SourceManifestError,
    detect_charset,
    fetch_source,
    load_sources,
    verify_raw_matches_sidecar,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=response
            )


class FakeClient:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def get(
        self,
        url: str,
        timeout: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(url)
        self.headers.append(dict(headers or {}))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, FakeResponse)
        return result


class NoNetworkClient:
    def get(
        self,
        url: str,
        timeout: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        raise AssertionError("fetch_source must not hit the network for an unchanged file")


def make_source(**overrides: object) -> Source:
    data: dict[str, object] = {
        "id": "lmp",
        "title": "Lei nº 11.340/2006 (Lei Maria da Penha)",
        "url": "https://example.test/lmp.htm",
        "parser": "planalto",
        "priority": "P0",
        "tipo": "lei",
        "enabled": True,
    }
    data.update(overrides)
    return Source.model_validate(data)


def test_load_sources_reads_manifest() -> None:
    sources = load_sources(FIXTURES / "sources_min.yaml")

    assert [source.id for source in sources] == ["lmp", "cpp"]
    assert sources[0].parser == "planalto"
    assert sources[0].priority == "P0"
    assert sources[0].enabled is True
    assert sources[1].enabled is False
    assert sources[1].sha256 is None


def test_load_sources_rejects_missing_required_field(tmp_path: Path) -> None:
    manifest = tmp_path / "bad.yaml"
    manifest.write_text("sources:\n  - id: x\n", encoding="utf-8")

    with pytest.raises(SourceManifestError, match="url"):
        load_sources(manifest)


def test_load_sources_rejects_duplicate_ids(tmp_path: Path) -> None:
    manifest = tmp_path / "dupes.yaml"
    manifest.write_text(
        "sources:\n"
        "  - id: lmp\n"
        "    title: A\n"
        "    url: https://example.test/a\n"
        "    parser: planalto\n"
        "    priority: P0\n"
        "    tipo: lei\n"
        "    enabled: true\n"
        "  - id: lmp\n"
        "    title: B\n"
        "    url: https://example.test/b\n"
        "    parser: planalto\n"
        "    priority: P0\n"
        "    tipo: lei\n"
        "    enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceManifestError, match="duplicate"):
        load_sources(manifest)


def test_fetch_writes_raw_bytes_without_decoding(tmp_path: Path) -> None:
    raw = "Lei com acentuação: ação".encode("cp1252")
    source = make_source()
    client = FakeClient(FakeResponse(200, raw, {"content-type": "text/html; charset=windows-1252"}))

    result = fetch_source(source, tmp_path, client=client)

    assert result.unchanged is False
    assert result.status_code == 200
    assert result.sha256 == sha256(raw)
    assert result.path.read_bytes() == raw

    meta = json.loads((tmp_path / "lmp.meta.json").read_text(encoding="utf-8"))
    assert meta["url"] == source.url
    assert meta["sha256"] == result.sha256
    assert meta["content_type"] == "text/html; charset=windows-1252"
    assert meta["status"] == 200
    assert "retrieved_at" in meta


def test_fetch_sends_an_identifiable_user_agent(tmp_path: Path) -> None:
    # planalto.gov.br blackholes the default httpx agent (no response), which
    # surfaced as a read timeout instead of HTTP 200.  Every download must
    # carry an explicit agent and the Portuguese accept-language.
    client = FakeClient(FakeResponse(200, b"<html>ok</html>"))

    fetch_source(make_source(), tmp_path, client=client)

    sent = client.headers[0]
    assert sent["User-Agent"] == USER_AGENT
    assert "python-httpx" not in sent["User-Agent"].lower()
    assert sent["Accept-Language"].startswith("pt-BR")


def test_fetch_extra_headers_override_defaults(tmp_path: Path) -> None:
    client = FakeClient(FakeResponse(200, b"ok"))

    fetch_source(make_source(), tmp_path, client=client, headers={"User-Agent": "custom/1"})

    assert client.headers[0]["User-Agent"] == "custom/1"
    assert client.headers[0]["Accept-Language"].startswith("pt-BR")


def test_verify_raw_matches_sidecar_rejects_a_truncated_file(tmp_path: Path) -> None:
    # data/raw/lmp.html was left holding 3 bytes ("raw") while its sidecar
    # still described the real page; --offline parsed the 3 bytes and reported
    # "no article found", blaming the parser.
    raw = b"<html>real page</html>"
    path = tmp_path / "lmp.html"
    path.write_bytes(b"raw")
    (tmp_path / "lmp.meta.json").write_text(
        json.dumps({"sha256": sha256(raw), "status": 200}), encoding="utf-8"
    )

    with pytest.raises(FetchError, match="does not match its download sidecar"):
        verify_raw_matches_sidecar(make_source(), path, tmp_path)


def test_verify_raw_matches_sidecar_accepts_matching_bytes(tmp_path: Path) -> None:
    raw = b"<html>real page</html>"
    path = tmp_path / "lmp.html"
    path.write_bytes(raw)
    (tmp_path / "lmp.meta.json").write_text(
        json.dumps({"sha256": sha256(raw), "status": 200}), encoding="utf-8"
    )

    verify_raw_matches_sidecar(make_source(), path, tmp_path)


def test_verify_raw_matches_sidecar_ignores_a_missing_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "lmp.html"
    path.write_bytes(b"anything")

    verify_raw_matches_sidecar(make_source(), path, tmp_path)


def test_fetch_is_idempotent_when_hash_matches(tmp_path: Path) -> None:
    raw = b"<html>same bytes</html>"
    source = make_source()
    first = fetch_source(source, tmp_path, client=FakeClient(FakeResponse(200, raw)))

    second = fetch_source(source, tmp_path, client=NoNetworkClient())

    assert second.unchanged is True
    assert second.sha256 == first.sha256
    assert second.path == first.path
    assert second.path.read_bytes() == raw


def test_fetch_is_idempotent_when_manifest_hash_matches(tmp_path: Path) -> None:
    raw = b"pinned bytes"
    source = make_source(sha256=sha256(raw))
    (tmp_path / "lmp.html").write_bytes(raw)

    result = fetch_source(source, tmp_path, client=NoNetworkClient())

    assert result.unchanged is True
    assert result.sha256 == sha256(raw)


def test_fetch_manifest_pin_mismatch_forces_download(tmp_path: Path) -> None:
    old = b"old bytes"
    new = b"new bytes"
    path = tmp_path / "lmp.html"
    path.write_bytes(old)
    (tmp_path / "lmp.meta.json").write_text(
        json.dumps({"sha256": sha256(old), "status": 200}),
        encoding="utf-8",
    )
    source = make_source(sha256=sha256(new))
    client = FakeClient(FakeResponse(200, new))

    result = fetch_source(source, tmp_path, client=client)

    assert result.unchanged is False
    assert result.sha256 == sha256(new)
    assert path.read_bytes() == new
    assert len(client.calls) == 1


def test_fetch_retries_on_server_error(tmp_path: Path) -> None:
    raw = b"ok"
    client = FakeClient(FakeResponse(500), FakeResponse(503), FakeResponse(200, raw))

    result = fetch_source(make_source(), tmp_path, client=client, retries=2, backoff=0)

    assert result.status_code == 200
    assert result.unchanged is False
    assert len(client.calls) == 3


def test_fetch_raises_when_retries_exhausted(tmp_path: Path) -> None:
    client = FakeClient(FakeResponse(500), FakeResponse(502))

    with pytest.raises(FetchError, match="lmp"):
        fetch_source(make_source(), tmp_path, client=client, retries=1, backoff=0)


def test_fetch_retries_on_timeout(tmp_path: Path) -> None:
    client = FakeClient(httpx.ReadTimeout("slow"), FakeResponse(200, b"ok"))

    result = fetch_source(make_source(), tmp_path, client=client, retries=1, backoff=0)

    assert result.status_code == 200
    assert len(client.calls) == 2


def test_fetch_raises_when_timeouts_exhausted(tmp_path: Path) -> None:
    client = FakeClient(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))

    with pytest.raises(FetchError, match="timeout"):
        fetch_source(make_source(), tmp_path, client=client, retries=1, backoff=0)


def test_fetch_does_not_retry_client_error(tmp_path: Path) -> None:
    client = FakeClient(FakeResponse(404))

    with pytest.raises(FetchError, match="404"):
        fetch_source(make_source(), tmp_path, client=client, retries=3, backoff=0)

    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b'<meta charset="iso-8859-1">ol\xe1', "iso-8859-1"),
        (
            b'<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">',
            "windows-1252",
        ),
        ("texto sem meta ção".encode(), "utf-8"),
        ("texto sem meta ção".encode("cp1252"), "cp1252"),
    ],
)
def test_detect_charset(raw: bytes, expected: str) -> None:
    assert detect_charset(raw) == expected


def test_detect_charset_ignores_unknown_declared_encoding() -> None:
    raw = b'<meta charset="x-unknown-charset">texto'

    assert detect_charset(raw) == "utf-8"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\xff\xfe" + "<html>Lei</html>".encode("utf-16-le"), "utf-16"),
        (b"\xfe\xff" + "<html>Lei</html>".encode("utf-16-be"), "utf-16"),
        (b"\xef\xbb\xbf" + b"<html>Lei</html>", "utf-8-sig"),
    ],
)
def test_detect_charset_honours_byte_order_mark(raw: bytes, expected: str) -> None:
    # planalto.gov.br serves the Lei Maria da Penha page as UTF-16LE with no
    # charset meta; decoding it as cp1252 produced text that parsed to zero
    # articles, so the BOM must win over every other signal.
    assert detect_charset(raw) == expected
    assert "<html>" in raw.decode(expected, errors="strict")


def test_detect_charset_bom_outranks_declared_meta() -> None:
    raw = b"\xef\xbb\xbf" + b'<meta charset="iso-8859-1">Lei'

    assert detect_charset(raw) == "utf-8-sig"


def test_detect_charset_recognises_utf16_without_bom() -> None:
    raw = "<html>Lei</html>  ".encode("utf-16-le")

    assert detect_charset(raw) == "utf-16"


def test_cli_parses_selection_flags() -> None:
    parser = run_module.build_parser()

    assert parser.parse_args(["--source", "lmp"]).source == "lmp"
    assert parser.parse_args(["--priority", "P0"]).priority == "P0"
    assert parser.parse_args(["--all"]).all is True


def test_cli_reports_manifest_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_module.main(
        [
            "--all",
            "--manifest",
            str(tmp_path / "missing.yaml"),
            "--dest-dir",
            str(tmp_path / "raw"),
        ]
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "missing.yaml" in err


def test_cli_returns_zero_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = tmp_path / "sources.yaml"
    manifest.write_text(
        "sources:\n"
        "  - id: lmp\n"
        "    title: LMP\n"
        "    url: https://example.test/lmp\n"
        "    parser: planalto\n"
        "    priority: P0\n"
        "    tipo: lei\n"
        "    enabled: true\n",
        encoding="utf-8",
    )

    def fake_fetch(source, dest_dir, **kwargs):
        from src.ingest.fetch import FetchResult

        path = Path(dest_dir) / f"{source.id}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return FetchResult(
            source_id=source.id,
            path=path,
            sha256=sha256(b"x"),
            unchanged=False,
            status_code=200,
        )

    monkeypatch.setattr(run_module, "fetch_source", fake_fetch)
    code = run_module.main(
        [
            "--all",
            "--stage",
            "download",
            "--manifest",
            str(manifest),
            "--dest-dir",
            str(tmp_path / "raw"),
        ]
    )

    assert code == 0


def test_cli_returns_one_when_enabled_source_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "sources.yaml"
    manifest.write_text(
        "sources:\n"
        "  - id: lmp\n"
        "    title: LMP\n"
        "    url: https://example.test/lmp\n"
        "    parser: planalto\n"
        "    priority: P0\n"
        "    tipo: lei\n"
        "    enabled: true\n",
        encoding="utf-8",
    )

    def fake_fetch(*args, **kwargs):
        raise FetchError("boom")

    monkeypatch.setattr(run_module, "fetch_source", fake_fetch)
    code = run_module.main(
        [
            "--all",
            "--stage",
            "download",
            "--manifest",
            str(manifest),
            "--dest-dir",
            str(tmp_path / "raw"),
        ]
    )

    assert code == 1
