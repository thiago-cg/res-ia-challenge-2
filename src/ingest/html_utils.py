from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "center",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "ol",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
_STRIKE_TAGS = {"del", "s", "strike"}
_SKIP_TAGS = {"script", "style"}


@dataclass
class RawLine:
    parts: list[tuple[str, bool]] = field(default_factory=list)

    def add(self, text: str, struck: bool) -> None:
        self.parts.append((text, struck))

    def vigente(self) -> str:
        return "".join(text for text, struck in self.parts if not struck)

    def anterior(self) -> str:
        return "".join(text for text, struck in self.parts if struck)

    def is_empty(self) -> bool:
        return not self.vigente().strip() and not self.anterior().strip()


class _LineParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[RawLine] = []
        self.title = ""
        self._current = RawLine()
        self._title_parts: list[str] = []
        self._in_title = False
        self._strike_depth = 0
        self._skip_depth = 0

    def _flush(self) -> None:
        if not self._current.is_empty():
            self.lines.append(self._current)
        self._current = RawLine()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _STRIKE_TAGS:
            self._strike_depth += 1
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _STRIKE_TAGS and self._strike_depth > 0:
            self._strike_depth -= 1
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
            self.title = collapse_whitespace(" ".join(self._title_parts))

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._current.add(data, self._strike_depth > 0)

    def handle_comment(self, data: str) -> None:
        return

    def close(self) -> None:
        super().close()
        self._flush()


def extract_lines(html_text: str) -> tuple[str, list[RawLine]]:
    parser = _LineParser()
    parser.feed(html_text)
    parser.close()
    return parser.title, parser.lines


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_ANNOTATION_RE = re.compile(
    r"\(\s*(?:"
    r"Reda[çc][ãa]o dada"
    r"|Inclu[íi]d[oa]"
    r"|Revogad[oa]"
    r"|Nova reda[çc][ãa]o"
    r"|NR"
    r"|Vide(?:\s+ADI)?"
    r")\b[^)]*\)",
    re.IGNORECASE,
)


def strip_annotations(text: str) -> tuple[str, list[str]]:
    annotations: list[str] = []

    def replace(match: re.Match[str]) -> str:
        inner = match.group(0).strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        annotations.append(collapse_whitespace(inner))
        return " "

    cleaned = _ANNOTATION_RE.sub(replace, text)
    return collapse_whitespace(cleaned), annotations


_TILDE_RE = re.compile(r"~~(.*?)~~", re.DOTALL)


def split_tilde_strikes(text: str) -> tuple[str, str]:
    struck: list[str] = []

    def replace(match: re.Match[str]) -> str:
        struck.append(match.group(1))
        return " "

    cleaned = _TILDE_RE.sub(replace, text)
    return collapse_whitespace(cleaned), collapse_whitespace(" ".join(struck))
