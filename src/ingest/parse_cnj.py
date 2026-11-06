from __future__ import annotations

from datetime import date
from pathlib import Path

from src.ingest.models import ParseResult
from src.ingest.parse_planalto import parse_html_document


def parse_cnj(source_id: str, path: str | Path, *, hoje: date | None = None) -> ParseResult:
    return parse_html_document(source_id, path, hoje=hoje, citation_style="cnj")
