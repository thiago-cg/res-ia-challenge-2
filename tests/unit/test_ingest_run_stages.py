from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from src.contracts import Device, DeviceVersion
from src.index.load_db import LoadReport
from src.ingest import run as run_module
from src.ingest.fetch import FetchResult
from src.ingest.models import Norm, ParseResult
from src.ingest.validate import ValidationReport

MANIFEST = """\
sources:
  - id: lmp
    title: LMP
    url: https://example.test/lmp.htm
    parser: planalto
    priority: P0
    tipo: lei
    enabled: true
"""


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(MANIFEST, encoding="utf-8")
    return path


def _parse_result() -> ParseResult:
    device = Device(
        id="lmp/art1",
        norm_id="lmp",
        parent_id=None,
        artigo_id="lmp/art1",
        tipo="artigo",
        rotulo="Art. 1",
        caminho="Art. 1",
        ordem=1,
    )
    version = DeviceVersion(
        device_id=device.id,
        norm_version_id=1,
        texto_literal="Texto literal.",
        texto_anterior=None,
        contexto="Contexto.",
        citacao="Lei nº 11.340/2006, art. 1º",
        vigencia_status="vigente",
        redacao_dada_por=None,
        vigencia_inicio=date(2006, 9, 22),
        vigencia_fim=None,
        fonte_url="https://example.test/lmp.htm",
        content_hash="placeholder",
        qdrant_point_id=uuid5(NAMESPACE_URL, device.id),
        search_text="",
    )
    return ParseResult(
        norm=Norm(id="lmp", tipo="lei", numero="11.340", ano=2006),
        devices=[device],
        versions=[version],
    )


class FakeConnection:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.closed = False

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.closed = True


def _fail(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("this stage must not run")


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    def fake_fetch(source: Any, dest_dir: Path, **kwargs: Any) -> FetchResult:
        events.append("download")
        path = Path(dest_dir) / f"{source.id}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raw", encoding="utf-8")
        return FetchResult(
            source_id=source.id,
            path=path,
            sha256="0" * 64,
            unchanged=False,
            status_code=200,
        )

    monkeypatch.setattr(run_module, "fetch_source", fake_fetch)


def _patch_parse(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    def fake_parse(source: Any, path: Path) -> ParseResult:
        events.append("parse")
        assert Path(path).is_file()
        return _parse_result()

    monkeypatch.setattr(run_module, "parse_downloaded_source", fake_parse)


def _patch_validate(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    def fake_validate(result: ParseResult) -> ValidationReport:
        events.append("validate")
        return ValidationReport()

    monkeypatch.setattr(run_module, "validate_parse_result", fake_validate)


def _patch_load(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    def fake_load(conn: Any, result: ParseResult, **kwargs: Any) -> LoadReport:
        events.append("load")
        return LoadReport(norm_id=result.norm.id, devices_loaded=1, versions_loaded=1)

    monkeypatch.setattr(run_module, "load_parse_result", fake_load)


def _patch_record(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    def fake_record(conn: Any, source_id: str, status: str, **kwargs: Any) -> int:
        events.append(f"record:{status}")
        return 1

    monkeypatch.setattr(run_module, "record_ingest_run", fake_record)


def test_download_stage_does_not_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    _patch_fetch(monkeypatch, events)
    monkeypatch.setattr(run_module, "parse_downloaded_source", _fail)
    monkeypatch.setattr(run_module, "_connect", _fail)

    code = run_module.main(["--all", "--stage", "download", "--manifest", str(_manifest(tmp_path))])

    assert code == 0
    assert events == ["download"]


def test_parse_stage_does_not_validate_or_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    _patch_fetch(monkeypatch, events)
    _patch_parse(monkeypatch, events)
    monkeypatch.setattr(run_module, "validate_parse_result", _fail)
    monkeypatch.setattr(run_module, "load_parse_result", _fail)
    monkeypatch.setattr(run_module, "_connect", _fail)

    code = run_module.main(["--all", "--stage", "parse", "--manifest", str(_manifest(tmp_path))])

    assert code == 0
    assert events == ["download", "parse"]


def test_offline_missing_raw_file_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run_module, "fetch_source", _fail)
    monkeypatch.setattr(run_module, "parse_downloaded_source", _fail)

    code = run_module.main(
        [
            "--all",
            "--offline",
            "--stage",
            "parse",
            "--manifest",
            str(_manifest(tmp_path)),
            "--dest-dir",
            str(tmp_path / "raw"),
        ]
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "raw file not found" in err
    assert "lmp" in err


def test_offline_parses_existing_raw_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    dest = tmp_path / "raw"
    dest.mkdir()
    (dest / "lmp.html").write_text("raw", encoding="utf-8")
    _patch_parse(monkeypatch, events)
    monkeypatch.setattr(run_module, "fetch_source", _fail)

    code = run_module.main(
        [
            "--all",
            "--offline",
            "--stage",
            "parse",
            "--manifest",
            str(_manifest(tmp_path)),
            "--dest-dir",
            str(dest),
        ]
    )

    assert code == 0
    assert events == ["parse"]


def test_load_failure_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    conn = FakeConnection()
    _patch_fetch(monkeypatch, events)
    _patch_parse(monkeypatch, events)
    _patch_validate(monkeypatch, events)
    _patch_record(monkeypatch, events)

    def failing_load(*args: Any, **kwargs: Any) -> LoadReport:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(run_module, "load_parse_result", failing_load)
    monkeypatch.setattr(run_module, "_connect", lambda url: conn)

    code = run_module.main(
        [
            "--all",
            "--manifest",
            str(_manifest(tmp_path)),
            "--database-url",
            "postgresql://example.test/db",
        ]
    )

    assert code == 1
    assert "database exploded" in capsys.readouterr().err
    assert "record:error" in events
    assert conn.closed is True


def test_all_stage_runs_stages_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    conn = FakeConnection(events)
    _patch_fetch(monkeypatch, events)
    _patch_parse(monkeypatch, events)
    _patch_validate(monkeypatch, events)
    _patch_load(monkeypatch, events)
    _patch_record(monkeypatch, events)

    def connect(url: str) -> FakeConnection:
        events.append("connect")
        return conn

    monkeypatch.setattr(run_module, "_connect", connect)

    code = run_module.main(
        [
            "--all",
            "--manifest",
            str(_manifest(tmp_path)),
            "--database-url",
            "postgresql://example.test/db",
        ]
    )

    assert code == 0
    assert events == [
        "connect",
        "download",
        "parse",
        "validate",
        "record:running",
        "load",
        "record:ok",
        "commit",
    ]
    assert conn.closed is True


def test_jsonl_output_is_atomic_and_parseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    _patch_fetch(monkeypatch, events)
    _patch_parse(monkeypatch, events)
    out_dir = tmp_path / "processed"

    code = run_module.main(
        [
            "--all",
            "--stage",
            "parse",
            "--manifest",
            str(_manifest(tmp_path)),
            "--out-jsonl",
            str(out_dir),
        ]
    )

    assert code == 0
    target = out_dir / "lmp.jsonl"
    assert target.is_file()
    assert not (out_dir / "lmp.jsonl.tmp").exists()
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["device_id"] == "lmp/art1"
    assert rows[0]["tipo"] == "artigo"
    assert rows[0]["norm_id"] == "lmp"
    assert rows[0]["ordem"] == 1
    assert rows[0]["norm"]["id"] == "lmp"


def test_jsonl_write_keeps_previous_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "lmp.jsonl"
    target.write_text("old\n", encoding="utf-8")

    def failing_replace(self: Path, destination: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        run_module.write_parse_result_jsonl(_parse_result(), target)

    assert target.read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / "lmp.jsonl.tmp").exists()


def test_parser_defaults_to_all_stage() -> None:
    parser = run_module.build_parser()
    args = parser.parse_args(["--all"])
    assert args.stage == "all"
    assert args.offline is False
    assert args.out_jsonl is None
