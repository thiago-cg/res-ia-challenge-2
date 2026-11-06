"""Ingestion CLI: download, parse, validate and load legal sources.

Stages are cumulative: ``parse`` also downloads (unless ``--offline``),
``validate`` also parses, and ``load``/``all`` run the whole pipeline. Every
source failure is reported and makes the command exit with status 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.index.load_db import load_parse_result, record_ingest_run, source_content_hash
from src.ingest.fetch import (
    FetchError,
    Source,
    SourceManifestError,
    _raw_filename,
    fetch_source,
    load_sources,
)
from src.ingest.models import ParseResult
from src.ingest.normalize import normalize_parse_result
from src.ingest.parse_cnj import parse_cnj
from src.ingest.parse_planalto import parse_source as parse_planalto_source
from src.ingest.parse_sumulas import parse_sumulas_pdf
from src.ingest.validate import validate_parse_result

ParserFn = Callable[[str, str | Path], ParseResult]

PARSERS: dict[str, ParserFn] = {
    "planalto": parse_planalto_source,
    "cnj": parse_cnj,
    "sumulas_pdf": parse_sumulas_pdf,
}

STAGES = ("download", "parse", "validate", "load", "all")
PARSE_STAGES = frozenset({"parse", "validate", "load", "all"})
LOAD_STAGES = frozenset({"load", "all"})

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "sources.yaml"
DEFAULT_DEST_DIR = PROJECT_ROOT / "data" / "raw"


class IngestStageError(Exception):
    pass


@dataclass
class SourceReport:
    source_id: str
    devices: int = 0
    changed: int = 0
    errors: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.errors == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingest.run",
        description="Download, parse, validate and load the enabled legal sources.",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--source", help="process a single source by id")
    selection.add_argument("--priority", choices=["P0", "P1"], help="process one priority tier")
    selection.add_argument("--all", action="store_true", help="process every enabled source")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest-dir", type=Path, default=DEFAULT_DEST_DIR)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--stage",
        choices=STAGES,
        default="all",
        help="last stage to run (default: all)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip download and parse the existing raw file; error when it is missing",
    )
    parser.add_argument(
        "--out-jsonl",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "write one atomic <source>.jsonl per source under PATH "
            "(a single source may pass a .jsonl file)"
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL for --stage load|all (default: $DATABASE_URL or Settings)",
    )
    return parser


def _select(sources: list[Source], args: argparse.Namespace) -> list[Source]:
    if args.source:
        selected = [source for source in sources if source.id == args.source]
        if not selected:
            raise FetchError(f"source not found in manifest: {args.source}")
        return selected
    if args.priority:
        return [source for source in sources if source.priority == args.priority]
    return list(sources)


def parse_downloaded_source(source: Source, path: str | Path) -> ParseResult:
    parser = PARSERS.get(source.parser)
    if parser is None:
        raise FetchError(f"no parser registered for {source.parser!r}")
    return parser(source.id, path)


def _validate_args(args: argparse.Namespace) -> str | None:
    if args.offline and args.stage not in PARSE_STAGES:
        return "--offline requires --stage parse, validate, load or all"
    if args.out_jsonl is not None and args.stage not in PARSE_STAGES:
        return "--out-jsonl requires --stage parse, validate, load or all"
    return None


def _database_url(args: argparse.Namespace) -> str:
    return args.database_url or os.environ.get("DATABASE_URL") or get_settings().database_url


def _connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(database_url)


def _raw_path(source: Source, dest_dir: Path) -> Path:
    return Path(dest_dir) / _raw_filename(source)


def _jsonl_target(base: Path, source: Source, *, single: bool) -> Path:
    if single and base.suffix.lower() == ".jsonl":
        return base
    return base / f"{source.id}.jsonl"


def write_parse_result_jsonl(result: ParseResult, path: Path) -> None:
    """Write one JSON line per device version, atomically."""

    devices = {device.id: device for device in result.devices}
    norm = result.norm.model_dump(mode="json")
    lines: list[str] = []
    for version in result.versions:
        payload = version.model_dump(mode="json")
        device = devices.get(version.device_id)
        if device is not None:
            identity = device.model_dump(mode="json")
            identity.pop("id", None)
            payload.update(identity)
        payload["norm"] = norm
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    text = "\n".join(lines) + ("\n" if lines else "")
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def _run_source(
    source: Source, args: argparse.Namespace, conn: Any, *, single: bool
) -> SourceReport:
    report = SourceReport(source_id=source.id)
    ingest_run_id: int | None = None
    try:
        if args.stage == "download":
            fetch_source(source, args.dest_dir, timeout=args.timeout, retries=args.retries)
            return report

        if args.offline:
            raw_path = _raw_path(source, args.dest_dir)
            if not raw_path.is_file():
                raise IngestStageError(
                    f"raw file not found for {source.id}: {raw_path}; run --stage download first"
                )
        else:
            raw_path = fetch_source(
                source,
                args.dest_dir,
                timeout=args.timeout,
                retries=args.retries,
            ).path

        parsed = parse_downloaded_source(source, raw_path)
        report.devices = len(parsed.devices)
        if args.out_jsonl is not None:
            write_parse_result_jsonl(
                parsed,
                _jsonl_target(args.out_jsonl, source, single=single),
            )
        if args.stage == "parse":
            return report

        validation = validate_parse_result(parsed)
        for warning in validation.warnings:
            print(f"WARN {source.id}: {warning}", file=sys.stderr)
        if not validation.ok:
            report.errors = len(validation.errors)
            report.error = "; ".join(validation.errors)
            return report
        if args.stage == "validate":
            return report

        if conn is None:
            report.errors = 1
            report.error = "database connection is not available"
            return report

        ingest_run_id = record_ingest_run(conn, source.id, "running")
        loaded = load_parse_result(conn, parsed, ingest_run_id=ingest_run_id)
        normalized = normalize_parse_result(parsed)
        record_ingest_run(
            conn,
            source.id,
            "ok",
            ingest_run_id=ingest_run_id,
            content_hash=source_content_hash(normalized.norm, normalized.versions),
        )
        conn.commit()
        report.changed = loaded.versions_loaded
        return report
    except Exception as exc:
        report.errors = max(report.errors, 1)
        report.error = str(exc) or type(exc).__name__
        _record_failure(conn, source.id, ingest_run_id, report.error)
        return report


def _record_failure(
    conn: Any,
    source_id: str,
    ingest_run_id: int | None,
    message: str,
) -> None:
    if conn is None or ingest_run_id is None:
        return
    try:
        conn.rollback()
    except Exception:
        pass
    try:
        record_ingest_run(
            conn,
            source_id,
            "error",
            ingest_run_id=ingest_run_id,
            error=message[:2000],
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _print_report(report: SourceReport) -> None:
    state = "OK  " if report.ok else "FAIL"
    print(
        f"{state} {report.source_id} devices={report.devices} "
        f"changed={report.changed} errors={report.errors}"
    )
    if report.error:
        print(f"     {report.error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    invalid = _validate_args(args)
    if invalid is not None:
        print(f"error: {invalid}", file=sys.stderr)
        return 1

    try:
        sources = load_sources(args.manifest)
        selected = _select(sources, args)
    except (FetchError, SourceManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    active: list[Source] = []
    for source in selected:
        if not source.enabled:
            print(f"SKIP {source.id} (disabled)")
            continue
        active.append(source)

    conn: Any = None
    if args.stage in LOAD_STAGES and active:
        database_url = _database_url(args)
        try:
            conn = _connect(database_url)
        except Exception as exc:
            print(f"error: could not connect to database: {exc}", file=sys.stderr)
            return 1

    failures = 0
    try:
        for source in active:
            report = _run_source(source, args, conn, single=len(active) == 1)
            _print_report(report)
            if not report.ok:
                failures += 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    print(f"done: {len(active) - failures}/{len(active)} ok")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
