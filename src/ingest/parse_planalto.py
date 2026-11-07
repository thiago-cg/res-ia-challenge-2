from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from src.contracts import Device, DeviceVersion
from src.ingest.fetch import detect_charset
from src.ingest.html_utils import (
    RawLine,
    collapse_whitespace,
    extract_lines,
    split_tilde_strikes,
    strip_annotations,
)
from src.ingest.models import (
    FRESH_NORM_VERSION_ID,
    Norm,
    ParseError,
    ParseResult,
    build_norm,
    close_version_windows,
    compute_content_hash,
    default_vigencia_inicio,
    known_source_date,
    norm_display,
    normalize_search_text,
    qdrant_point_id,
)

CitationStyle = Literal["planalto", "cnj"]

_TITULO_RE = re.compile(r"^T[ÍI]TULO\s+([IVXLCDM]+)\b\s*(?:[-–—]\s*)?(.*)$", re.IGNORECASE)
_CAPITULO_RE = re.compile(r"^CAP[ÍI]TULO\s+([IVXLCDM]+)\b\s*(?:[-–—]\s*)?(.*)$", re.IGNORECASE)
_SECAO_RE = re.compile(r"^SE[ÇC][ÃA]O\s+([IVXLCDM]+)\b\s*(?:[-–—]\s*)?(.*)$", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"^Art\.\s*(\d+(?:-[A-Za-z])?)\s*[ºo°]?\s*[.\-–—]?\s*(.*)$", re.IGNORECASE)
_PAR_UNICO_RE = re.compile(r"^Par[áa]grafo\s+[úu]nico\b\.?\s*(.*)$", re.IGNORECASE)
_PAR_RE = re.compile(r"^§\s*(\d+)\s*[ºo°]?\s*[.\-–—]?\s*(.*)$")
_INCISO_RE = re.compile(r"^([IVXLCDM]+)\s*[-–—]\s*(.*)$", re.IGNORECASE)
_ALINEA_RE = re.compile(r"^([a-z])\s*[.)]{1,2}\s+(.*)$")
_ITEM_RE = re.compile(r"^(\d+)\s*[.)]{1,2}\s+(.*)$")

_HEADING_ORDER = ("titulo", "capitulo", "secao")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_FULL_DATE_RE = re.compile(r"\b(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_LAW_REF_RE = re.compile(
    r"(?:Lei(?:\s+Complementar)?|Decreto(?:-Lei)?)\s+n[ºo°]?\s*([\d.]+)"
    r"\s*(?:,\s*de\s*|/)\s*(\d{4})",
    re.IGNORECASE,
)


def resolve_annotation_date(annotation: str) -> tuple[date | None, bool]:
    """Return (date, exact). Year-only dates use Dec 31 as a conservative bound."""
    full = _FULL_DATE_RE.search(annotation)
    if full is not None:
        month = _MONTHS.get(full.group(2).lower())
        if month is not None:
            try:
                return date(int(full.group(3)), month, int(full.group(1))), True
            except ValueError:
                pass

    law = _LAW_REF_RE.search(annotation)
    if law is not None:
        exact = known_source_date(law.group(1), int(law.group(2)))
        if exact is not None:
            return exact, True

    years = [int(match.group(0)) for match in _YEAR_RE.finditer(annotation)]
    if years:
        return date(years[-1], 12, 31), False
    return None, False


def roman_to_int(value: str) -> int | None:
    value = value.upper()
    if not value or any(char not in _ROMAN_VALUES for char in value):
        return None
    total = 0
    previous = 0
    for char in reversed(value):
        current = _ROMAN_VALUES[char]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total or None


@dataclass
class _Node:
    id: str
    tipo: str
    artigo_id: str
    parent_id: str | None
    rotulo: str
    ordem: int
    citacao_levels: list[str]
    contexto_levels: list[str]
    short_levels: list[str]
    headings_display: list[str]
    headings_short: list[str]
    vigencia_inicio: date
    texto_parts: list[str] = field(default_factory=list)
    anterior_parts: list[str] = field(default_factory=list)
    status: str = "vigente"
    redacao: str | None = None
    vigencia_fim: date | None = None

    @property
    def caminho(self) -> str:
        return " > ".join(self.headings_short + self.short_levels)


class _StructuralParser:
    def __init__(self, *, norm: Norm, citation_style: CitationStyle) -> None:
        self.norm = norm
        self.citation_style = citation_style
        self.nodes: list[_Node] = []
        self.by_id: dict[str, _Node] = {}
        self.warnings: list[str] = []
        self.remissoes: list[str] = []
        self.headings: dict[str, tuple[str, str]] = {}
        self.current_article: _Node | None = None
        self.current_caput: _Node | None = None
        self.current_paragraph: _Node | None = None
        self.current_inciso: _Node | None = None
        self.current_alinea: _Node | None = None
        self.current_node: _Node | None = None
        self.last_node: _Node | None = None
        self.article_seen = False
        self.vigencia_inicio = default_vigencia_inicio(norm.id, ano=norm.ano)

    @property
    def headings_display(self) -> list[str]:
        return [self.headings[key][0] for key in _HEADING_ORDER if key in self.headings]

    @property
    def headings_short(self) -> list[str]:
        return [self.headings[key][1] for key in _HEADING_ORDER if key in self.headings]

    def _create(
        self,
        *,
        node_id: str,
        tipo: str,
        parent: _Node | None,
        rotulo: str,
        citacao_label: str,
        contexto_label: str,
        short_label: str,
        artigo_id: str,
    ) -> _Node:
        if parent is None:
            citacao_levels: list[str] = []
            contexto_levels: list[str] = []
            short_levels: list[str] = []
            headings_display = self.headings_display
            headings_short = self.headings_short
        else:
            citacao_levels = list(parent.citacao_levels)
            contexto_levels = list(parent.contexto_levels)
            short_levels = list(parent.short_levels)
            headings_display = list(parent.headings_display)
            headings_short = list(parent.headings_short)

        citacao_levels.append(citacao_label)
        contexto_levels.append(contexto_label)
        if short_label:
            short_levels.append(short_label)

        node = _Node(
            id=node_id,
            tipo=tipo,
            artigo_id=artigo_id,
            parent_id=parent.id if parent is not None else None,
            rotulo=rotulo,
            ordem=len(self.nodes) + 1,
            citacao_levels=citacao_levels,
            contexto_levels=contexto_levels,
            short_levels=short_levels,
            headings_display=headings_display,
            headings_short=headings_short,
            vigencia_inicio=self.vigencia_inicio,
        )
        self.nodes.append(node)
        self.by_id[node.id] = node
        self.last_node = node
        return node

    def _append(self, node: _Node, text: str, struck: str) -> None:
        if text:
            node.texto_parts.append(text)
        if struck:
            node.anterior_parts.append(struck)

        if node.tipo == "caput" and node.parent_id is not None:
            parent = self.by_id.get(node.parent_id)
            if parent is not None:
                if text:
                    parent.texto_parts.append(text)
                if struck:
                    parent.anterior_parts.append(struck)

    def _warn_once(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _apply_status(self, node: _Node, annotation: str) -> None:
        low = annotation.lower()
        if low.startswith("vide"):
            if annotation not in self.remissoes:
                self.remissoes.append(annotation)
            return

        event_date, exact = resolve_annotation_date(annotation)
        if low.startswith("revogad"):
            node.status = "revogado"
            node.redacao = annotation
            if event_date is not None:
                node.vigencia_fim = event_date
                if not exact:
                    self._warn_once(
                        f"{node.id}: revocation note has only a year; "
                        f"using {event_date.isoformat()}"
                    )
            return

        if low == "nr" or "reda" in low or low.startswith("inclu"):
            if node.status != "revogado":
                node.status = "alterado"
            node.redacao = annotation
            if event_date is not None:
                node.vigencia_inicio = event_date
                if not exact:
                    self._warn_once(
                        f"{node.id}: amendment note has only a year; using {event_date.isoformat()}"
                    )
            elif low != "nr":
                self._warn_once(f"{node.id}: amendment note has no date; keeping norm start date")

    def _annotate(self, node: _Node, annotations: list[str]) -> None:
        targets = [node]
        if node.tipo == "caput" and node.parent_id is not None:
            parent = self.by_id.get(node.parent_id)
            if parent is not None:
                targets.append(parent)
        for target in targets:
            for annotation in annotations:
                self._apply_status(target, annotation)

    def _set_heading(self, key: str, display: str, short: str) -> None:
        self.headings[key] = (display, short)
        if key == "titulo":
            self.headings.pop("capitulo", None)
            self.headings.pop("secao", None)
        elif key == "capitulo":
            self.headings.pop("secao", None)

        self.current_article = None
        self.current_caput = None
        self.current_paragraph = None
        self.current_inciso = None
        self.current_alinea = None
        self.current_node = None

    def _match_heading(self, text: str) -> tuple[str, str, str] | None:
        patterns = (
            ("titulo", "Título", _TITULO_RE),
            ("capitulo", "Capítulo", _CAPITULO_RE),
            ("secao", "Seção", _SECAO_RE),
        )
        for key, label, pattern in patterns:
            match = pattern.match(text)
            if match is None or roman_to_int(match.group(1)) is None:
                continue
            roman = match.group(1).upper()
            rest = collapse_whitespace(match.group(2))
            display = f"{label} {roman}" + (f" — {rest}" if rest else "")
            return key, display, f"{label} {roman}"
        return None

    def _article_citacao_label(self, numero: str) -> str:
        if self.citation_style == "cnj":
            return f"art. {numero}º"
        return f"art. {numero}"

    def _start_article(self, raw_numero: str, rest: str) -> _Node:
        # The article-level literal intentionally mirrors the caput literal.
        # Assembling the full article (caput + incisos) is IDX-01's job; the
        # parser must not fabricate a combined literal here.
        numero = raw_numero.strip()
        numero_id = numero.lower()
        artigo_id = f"{self.norm.id}/art{numero_id}"
        rotulo = f"Art. {numero}"
        citacao_label = self._article_citacao_label(numero)
        article = self._create(
            node_id=artigo_id,
            tipo="artigo",
            parent=None,
            rotulo=rotulo,
            citacao_label=citacao_label,
            contexto_label=rotulo,
            short_label=rotulo,
            artigo_id=artigo_id,
        )
        caput = self._create(
            node_id=f"{artigo_id}/cpt",
            tipo="caput",
            parent=article,
            rotulo="caput",
            citacao_label="caput",
            contexto_label="caput",
            short_label="",
            artigo_id=artigo_id,
        )
        self.current_article = article
        self.current_caput = caput
        self.current_paragraph = None
        self.current_inciso = None
        self.current_alinea = None
        self.current_node = caput
        self.article_seen = True
        return caput

    def _start_paragraph(
        self, suffix: str, rotulo: str, citacao_label: str, parent: _Node
    ) -> _Node:
        node = self._create(
            node_id=f"{parent.artigo_id}/{suffix}",
            tipo="paragrafo",
            parent=parent,
            rotulo=rotulo,
            citacao_label=citacao_label,
            contexto_label=rotulo,
            short_label=rotulo,
            artigo_id=parent.artigo_id,
        )
        self.current_paragraph = node
        self.current_inciso = None
        self.current_alinea = None
        self.current_node = node
        return node

    def feed(self, line: RawLine) -> None:
        base = collapse_whitespace(line.vigente())
        anterior = collapse_whitespace(line.anterior())

        base, tilde_struck = split_tilde_strikes(base)
        anterior = collapse_whitespace(" ".join(part for part in (anterior, tilde_struck) if part))
        base, annotations = strip_annotations(base)
        base = collapse_whitespace(base)

        if not base and not anterior:
            if annotations and (self.current_node is not None or self.last_node is not None):
                self._annotate(self.current_node or self.last_node, annotations)  # type: ignore[arg-type]
            return

        heading = self._match_heading(base)
        if heading is not None:
            self._set_heading(*heading)
            return

        article = _ARTICLE_RE.match(base)
        if article is not None:
            caput = self._start_article(article.group(1), collapse_whitespace(article.group(2)))
            self._append(caput, collapse_whitespace(article.group(2)), anterior)
            self._annotate(caput, annotations)
            return

        paragraph_unico = _PAR_UNICO_RE.match(base)
        if paragraph_unico is not None:
            parent = self.current_article or self.current_caput
            if parent is None:
                self._orphan(base, anterior, annotations)
                return
            node = self._start_paragraph("par-unico", "Parágrafo único", "parágrafo único", parent)
            self._append(node, collapse_whitespace(paragraph_unico.group(1)), anterior)
            self._annotate(node, annotations)
            return

        paragraph = _PAR_RE.match(base)
        if paragraph is not None:
            parent = self.current_article or self.current_caput
            if parent is None:
                self._orphan(base, anterior, annotations)
                return
            number = int(paragraph.group(1))
            node = self._start_paragraph(f"par{number}", f"§ {number}º", f"§ {number}º", parent)
            self._append(node, collapse_whitespace(paragraph.group(2)), anterior)
            self._annotate(node, annotations)
            return

        inciso = _INCISO_RE.match(base)
        if inciso is not None and roman_to_int(inciso.group(1)) is not None:
            parent = self.current_paragraph or self.current_caput or self.current_article
            if parent is None:
                self._orphan(base, anterior, annotations)
                return
            roman = inciso.group(1).upper()
            inciso_number = roman_to_int(roman)
            assert inciso_number is not None
            artigo_id = parent.artigo_id
            node = self._create(
                node_id=f"{parent.id}/inc{inciso_number}",
                tipo="inciso",
                parent=parent,
                rotulo=f"inciso {roman}",
                citacao_label=f"inciso {roman}",
                contexto_label=f"inciso {roman}",
                short_label=roman,
                artigo_id=artigo_id,
            )
            self.current_inciso = node
            self.current_alinea = None
            self.current_node = node
            self._append(node, collapse_whitespace(inciso.group(2)), anterior)
            self._annotate(node, annotations)
            return

        alinea = _ALINEA_RE.match(base)
        if alinea is not None:
            parent = self.current_inciso or self.current_paragraph or self.current_caput
            if parent is None:
                self._orphan(base, anterior, annotations)
                return
            letter = alinea.group(1)
            node = self._create(
                node_id=f"{parent.id}/ali-{letter}",
                tipo="alinea",
                parent=parent,
                rotulo=f'alínea "{letter}"',
                citacao_label=f'alínea "{letter}"',
                contexto_label=f'alínea "{letter}"',
                short_label=letter,
                artigo_id=parent.artigo_id,
            )
            self.current_alinea = node
            self.current_node = node
            self._append(node, collapse_whitespace(alinea.group(2)), anterior)
            self._annotate(node, annotations)
            return

        item = _ITEM_RE.match(base)
        if item is not None:
            parent = self.current_alinea or self.current_inciso or self.current_paragraph
            if parent is None:
                self._orphan(base, anterior, annotations)
                return
            number = int(item.group(1))
            node = self._create(
                node_id=f"{parent.id}/item-{number}",
                tipo="item",
                parent=parent,
                rotulo=f"item {number}",
                citacao_label=f"item {number}",
                contexto_label=f"item {number}",
                short_label=str(number),
                artigo_id=parent.artigo_id,
            )
            self.current_node = node
            self._append(node, collapse_whitespace(item.group(2)), anterior)
            self._annotate(node, annotations)
            return

        if self.current_node is not None:
            self._append(self.current_node, base, anterior)
            self._annotate(self.current_node, annotations)
        elif annotations and self.last_node is not None:
            self._annotate(self.last_node, annotations)
        elif self.article_seen:
            self.warnings.append(f"orphan text: {base[:60]}")

    def _orphan(self, base: str, anterior: str, annotations: list[str]) -> None:
        if self.current_node is not None:
            self._append(self.current_node, base, anterior)
            self._annotate(self.current_node, annotations)
        else:
            self.warnings.append(f"orphan text without parent: {base[:60]}")

    def build_result(self) -> ParseResult:
        devices_by_id: dict[str, Device] = {}
        versions: list[DeviceVersion] = []
        norm_title = norm_display(self.norm)

        for node in self.nodes:
            literal = collapse_whitespace(" ".join(node.texto_parts))
            anterior = collapse_whitespace(" ".join(node.anterior_parts)) or None
            if node.id not in devices_by_id:
                devices_by_id[node.id] = Device(
                    id=node.id,
                    norm_id=self.norm.id,
                    parent_id=node.parent_id,
                    artigo_id=node.artigo_id,
                    tipo=node.tipo,  # type: ignore[arg-type]
                    rotulo=node.rotulo,
                    caminho=node.caminho,
                    ordem=node.ordem,
                )
            if not literal:
                self.warnings.append(f"{node.id}: empty literal text was not indexed")
                continue

            vigencia_inicio = node.vigencia_inicio
            vigencia_fim = node.vigencia_fim
            if vigencia_fim is not None and vigencia_fim < vigencia_inicio:
                fallback = default_vigencia_inicio(self.norm.id, ano=self.norm.ano)
                vigencia_inicio = min(fallback, vigencia_fim)
                self.warnings.append(
                    f"{node.id}: revocation {vigencia_fim.isoformat()} precedes version "
                    f"start {node.vigencia_inicio.isoformat()}; using {vigencia_inicio.isoformat()}"
                )
            contexto = "\n".join(
                [norm_title, *node.headings_display, ", ".join(node.contexto_levels)]
            )
            citacao = f"{norm_title}, {', '.join(node.citacao_levels)}"
            search_text = normalize_search_text(f"{contexto}\n{literal}")
            content_hash = compute_content_hash(
                device_id=node.id,
                artigo_id=node.artigo_id,
                parent_id=node.parent_id,
                tipo=node.tipo,
                rotulo=node.rotulo,
                caminho=node.caminho,
                contexto=contexto,
                citacao=citacao,
                texto_literal=literal,
                texto_anterior=anterior,
                vigencia_status=node.status,
                redacao_dada_por=node.redacao,
                vigencia_inicio=vigencia_inicio,
                vigencia_fim=vigencia_fim,
                fonte_url=self.norm.fonte_url,
            )

            versions.append(
                DeviceVersion(
                    device_id=node.id,
                    norm_version_id=FRESH_NORM_VERSION_ID,
                    texto_literal=literal,
                    texto_anterior=anterior,
                    contexto=contexto,
                    citacao=citacao,
                    vigencia_status=node.status,  # type: ignore[arg-type]
                    redacao_dada_por=node.redacao,
                    vigencia_inicio=vigencia_inicio,
                    vigencia_fim=vigencia_fim,
                    fonte_url=self.norm.fonte_url,
                    content_hash=content_hash,
                    qdrant_point_id=qdrant_point_id(node.id),
                    search_text=search_text,
                )
            )

        devices = list(devices_by_id.values())
        closed = close_version_windows(versions)
        rehashed = [
            version.model_copy(
                update={"content_hash": _version_hash(version, devices_by_id[version.device_id])}
            )
            for version in closed
        ]
        return ParseResult(
            norm=self.norm,
            devices=devices,
            versions=rehashed,
            warnings=self.warnings,
            remissoes=self.remissoes,
        )


def _version_hash(version: DeviceVersion, device: Device) -> str:
    return compute_content_hash(
        device_id=device.id,
        artigo_id=device.artigo_id,
        parent_id=device.parent_id,
        tipo=device.tipo,
        rotulo=device.rotulo,
        caminho=device.caminho,
        contexto=version.contexto,
        citacao=version.citacao,
        texto_literal=version.texto_literal,
        texto_anterior=version.texto_anterior,
        vigencia_status=version.vigencia_status,
        redacao_dada_por=version.redacao_dada_por,
        vigencia_inicio=version.vigencia_inicio,
        vigencia_fim=version.vigencia_fim,
        fonte_url=version.fonte_url,
    )


def parse_html_document(
    source_id: str,
    path: str | Path,
    *,
    hoje: date | None = None,
    citation_style: CitationStyle = "planalto",
    norm: Norm | None = None,
) -> ParseResult:
    raw = Path(path).read_bytes()
    if not raw.strip():
        raise ParseError(f"{source_id}: empty document")

    charset = detect_charset(raw)
    html_text = raw.decode(charset, errors="replace")
    title, lines = extract_lines(html_text)
    if norm is None:
        norm = build_norm(source_id, title=title)

    # `hoje` is accepted for API compatibility only. Parse time must never
    # leak into vigência fields or content_hash.
    parser = _StructuralParser(norm=norm, citation_style=citation_style)
    for line in lines:
        parser.feed(line)

    if not parser.article_seen:
        raise ParseError(f"{source_id}: no article found in {path}")

    return parser.build_result()


def parse_source(source_id: str, path: str | Path, *, hoje: date | None = None) -> ParseResult:
    return parse_html_document(source_id, path, hoje=hoje, citation_style="planalto")
