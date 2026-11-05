from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from src.ingest.fetch import (
    FetchError,
    Source,
    SourceManifestError,
    fetch_source,
    load_sources,
)
from src.ingest.models import ParseResult
from src.ingest.parse_cnj import parse_cnj
from src.ingest.parse_planalto import parse_source as parse_planalto_source
from src.ingest.parse_sumulas import parse_sumulas_pdf

ParserFn = Callable[[str, str | Path], ParseResult]

PARSERS: dict[str, ParserFn] = {
    "planalto": parse_planalto_source,
    "cnj": parse_cnj,
    "sumulas_pdf": parse_sumulas_pdf,
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "sources.yaml"
DEFAULT_DEST_DIR = PROJECT_ROOT / "data" / "raw"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingest.run",
        description="Download the enabled legal sources from the manifest.",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--source", help="download a single source by id")
    selection.add_argument("--priority", choices=["P0", "P1"], help="download one priority tier")
    selection.add_argument("--all", action="store_true", help="download every enabled source")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest-dir", type=Path, default=DEFAULT_DEST_DIR)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        sources = load_sources(args.manifest)
        selected = _select(sources, args)
    except (FetchError, SourceManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    failures = 0
    ran = 0
    for source in selected:
        if not source.enabled:
            print(f"SKIP {source.id} (disabled)")
            continue
        ran += 1
        try:
            result = fetch_source(
                source,
                args.dest_dir,
                timeout=args.timeout,
                retries=args.retries,
            )
        except FetchError as exc:
            failures += 1
            print(f"FAIL {source.id}: {exc}")
        else:
            state = "unchanged" if result.unchanged else "downloaded"
            print(f"OK   {source.id} {result.status_code} {state} {result.sha256[:12]}")

    ok = ran - failures
    print(f"done: {ok}/{ran} ok")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
