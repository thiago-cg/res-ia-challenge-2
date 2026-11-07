from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field

from src.contracts import Device, DeviceVersion

NAMESPACE = NAMESPACE_URL
FRESH_NORM_VERSION_ID = 1


class ParseError(Exception):
    pass


class Norm(BaseModel):
    id: str
    tipo: str
    numero: str | None = None
    ano: int | None = None
    apelido: str | None = None
    ementa: str | None = None
    urn_lexml: str | None = None
    fonte_url: str = ""


class ParseResult(BaseModel):
    norm: Norm
    devices: list[Device] = Field(default_factory=list)
    versions: list[DeviceVersion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    remissoes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _SourceNorm:
    tipo: str
    numero: str | None
    ano: int | None
    apelido: str | None
    urn_lexml: str | None
    fonte_url: str
    vigencia_inicio: date
    data_exata: bool = True


# Single source of truth for publication/vigência dates.
# `data_exata=False` means only the publication year is known, so the date is
# deliberately conservative: Dec 31 of that year. Never move a placeholder
# earlier than the publication year end, or an amendment could be exposed
# before it was published.
SOURCE_NORMS: dict[str, _SourceNorm] = {
    "lmp": _SourceNorm(
        tipo="lei",
        numero="11.340",
        ano=2006,
        apelido="Lei Maria da Penha",
        urn_lexml="urn:lex:br:federal:lei:2006-08-07;11340",
        fonte_url="https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
        vigencia_inicio=date(2006, 9, 22),
    ),
    "cp": _SourceNorm(
        tipo="decreto-lei",
        numero="2.848",
        ano=1940,
        apelido="Código Penal",
        urn_lexml="urn:lex:br:federal:decreto-lei:1940-12-07;2848",
        fonte_url="https://www.planalto.gov.br/ccivil_03/decreto-lei/del2848compilado.htm",
        vigencia_inicio=date(1940, 12, 7),
    ),
    "cpp": _SourceNorm(
        tipo="decreto-lei",
        numero="3.689",
        ano=1941,
        apelido="Código de Processo Penal",
        urn_lexml="urn:lex:br:federal:decreto-lei:1941-10-03;3689",
        fonte_url="https://www.planalto.gov.br/ccivil_03/decreto-lei/del3689compilado.htm",
        vigencia_inicio=date(1941, 10, 3),
    ),
    "lei-15438-2026": _SourceNorm(
        tipo="lei",
        numero="15.438",
        ano=2026,
        apelido=None,
        urn_lexml=None,
        fonte_url="https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2026/lei/l15438.htm",
        vigencia_inicio=date(2026, 6, 18),
    ),
    "lei-14994-2024": _SourceNorm(
        tipo="lei",
        numero="14.994",
        ano=2024,
        apelido=None,
        urn_lexml=None,
        fonte_url="https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2024/lei/l14994.htm",
        vigencia_inicio=date(2024, 10, 9),
    ),
    "cf": _SourceNorm(
        tipo="constituicao",
        numero=None,
        ano=1988,
        apelido="Constituição Federal de 1988",
        urn_lexml="urn:lex:br:federal:constituicao:1988-10-05;1988",
        fonte_url="https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm",
        vigencia_inicio=date(1988, 10, 5),
    ),
    "lgpd": _SourceNorm(
        tipo="lei",
        numero="13.709",
        ano=2018,
        apelido="LGPD",
        urn_lexml="urn:lex:br:federal:lei:2018-08-14;13709",
        fonte_url="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/L13709.htm",
        vigencia_inicio=date(2020, 9, 1),
    ),
    "lda": _SourceNorm(
        tipo="lei",
        numero="9.610",
        ano=1998,
        apelido="Lei de Direitos Autorais",
        urn_lexml="urn:lex:br:federal:lei:1998-02-19;9610",
        fonte_url="https://www.planalto.gov.br/ccivil_03/leis/l9610.htm",
        vigencia_inicio=date(1998, 2, 19),
    ),
    "cnj-rc-5-2020": _SourceNorm(
        tipo="resolucao_conjunta",
        numero="5",
        ano=2020,
        apelido=None,
        urn_lexml=None,
        fonte_url="https://atos.cnj.jus.br/atos/detalhar/3218",
        vigencia_inicio=date(2020, 12, 31),
        data_exata=False,
    ),
    "cnj-portaria-6-2025": _SourceNorm(
        tipo="portaria_conjunta",
        numero="6",
        ano=2025,
        apelido=None,
        urn_lexml=None,
        fonte_url="https://atos.cnj.jus.br/atos/detalhar/6242",
        vigencia_inicio=date(2025, 12, 31),
        data_exata=False,
    ),
    "stj-sumulas": _SourceNorm(
        tipo="sumula",
        numero=None,
        ano=None,
        apelido="Súmulas do STJ",
        urn_lexml=None,
        fonte_url="https://scon.stj.jus.br/SCON/sumstj/",
        vigencia_inicio=date(1989, 1, 1),
        data_exata=False,
    ),
}

_TYPE_LABELS = {
    "lei": "Lei",
    "decreto-lei": "Decreto-Lei",
    "lei complementar": "Lei Complementar",
    "constituicao": "Constituição",
    "resolucao_conjunta": "Resolução Conjunta CNJ/CNMP",
    "portaria_conjunta": "Portaria Conjunta",
    "sumula": "Súmula",
}

_TITLE_RE = re.compile(
    r"(?P<tipo>Lei Complementar|Lei|Decreto-Lei|Decreto)\s+"
    r"n[ºo°]?\s*(?P<numero>[\d.]+)\s*/\s*(?P<ano>\d{4})",
    re.IGNORECASE,
)
_APELIDO_RE = re.compile(r"\((?P<apelido>[^)]+)\)")


def _norm_from_title(source_id: str, title: str | None) -> Norm:
    if not title:
        return Norm(id=source_id, tipo="lei")
    match = _TITLE_RE.search(title)
    if not match:
        return Norm(id=source_id, tipo="lei")
    apelido_match = _APELIDO_RE.search(title)
    return Norm(
        id=source_id,
        tipo=match.group("tipo").lower(),
        numero=match.group("numero"),
        ano=int(match.group("ano")),
        apelido=apelido_match.group("apelido").strip() if apelido_match else None,
    )


def build_norm(source_id: str, *, title: str | None = None, fonte_url: str | None = None) -> Norm:
    meta = SOURCE_NORMS.get(source_id)
    if meta is None:
        norm = _norm_from_title(source_id, title)
        norm.fonte_url = fonte_url or ""
        return norm
    return Norm(
        id=source_id,
        tipo=meta.tipo,
        numero=meta.numero,
        ano=meta.ano,
        apelido=meta.apelido,
        urn_lexml=meta.urn_lexml,
        fonte_url=fonte_url or meta.fonte_url,
    )


def known_source_date(numero: str, ano: int) -> date | None:
    """Return the exact publication date when the cited law is in the manifest."""
    for meta in SOURCE_NORMS.values():
        if meta.numero == numero and meta.ano == ano and meta.data_exata:
            return meta.vigencia_inicio
    return None


def default_vigencia_inicio(source_id: str, *, ano: int | None = None) -> date:
    meta = SOURCE_NORMS.get(source_id)
    if meta is not None:
        return meta.vigencia_inicio
    if ano is not None:
        return date(ano, 12, 31)
    return date(1970, 1, 1)


def norm_display(norm: Norm) -> str:
    if norm.tipo == "constituicao" and norm.apelido:
        return norm.apelido
    label = _TYPE_LABELS.get(norm.tipo, norm.tipo.replace("_", " ").title())
    if norm.numero and norm.ano:
        base = f"{label} nº {norm.numero}/{norm.ano}"
    elif norm.numero:
        base = f"{label} nº {norm.numero}"
    else:
        base = label
    if norm.apelido:
        base = f"{base} ({norm.apelido})"
    return base


def normalize_search_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents).strip().lower()


def compute_content_hash(
    *,
    device_id: str,
    artigo_id: str,
    parent_id: str | None,
    tipo: str,
    rotulo: str,
    caminho: str,
    contexto: str,
    citacao: str,
    texto_literal: str,
    texto_anterior: str | None,
    vigencia_status: str,
    redacao_dada_por: str | None,
    vigencia_inicio: date,
    vigencia_fim: date | None,
    fonte_url: str,
) -> str:
    metadata = "\n".join(
        [
            device_id,
            artigo_id,
            parent_id or "",
            tipo,
            rotulo,
            caminho,
            contexto,
            citacao,
            texto_literal,
            texto_anterior or "",
            vigencia_status,
            redacao_dada_por or "",
            vigencia_inicio.isoformat(),
            vigencia_fim.isoformat() if vigencia_fim else "",
            fonte_url,
        ]
    )
    return hashlib.sha256(metadata.encode("utf-8")).hexdigest()


def qdrant_point_id(device_id: str, norm_version_id: int = FRESH_NORM_VERSION_ID) -> UUID:
    return uuid5(NAMESPACE, f"{device_id}@{norm_version_id}")
