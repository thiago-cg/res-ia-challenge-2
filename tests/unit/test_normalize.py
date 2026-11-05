from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from src.contracts import Device, DeviceVersion
from src.ingest.models import Norm, ParseResult
from src.ingest.normalize import build_search_text, content_hash, normalize_parse_result
from src.ingest.parse_planalto import parse_source
from src.textnorm import normalize_search_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lmp_art22.html"


def _device() -> Device:
    return Device(
        id="lmp/art7",
        norm_id="lmp",
        parent_id=None,
        artigo_id="lmp/art7",
        tipo="artigo",
        rotulo="Art. 7",
        caminho="Art. 7",
        ordem=1,
    )


def _version(texto: str = "Texto com ação e violência.") -> DeviceVersion:
    return DeviceVersion(
        device_id="lmp/art7",
        norm_version_id=1,
        texto_literal=texto,
        texto_anterior=None,
        contexto="Lei nº 11.340/2006",
        citacao="Lei nº 11.340/2006, art. 7º",
        vigencia_status="vigente",
        redacao_dada_por=None,
        vigencia_inicio=date(2006, 9, 22),
        vigencia_fim=None,
        fonte_url="https://example.test",
        content_hash="old",
        qdrant_point_id=uuid5(NAMESPACE_URL, "lmp/art7@1"),
        search_text="",
    )


def _result(version: DeviceVersion | None = None) -> ParseResult:
    return ParseResult(
        norm=Norm(id="lmp", tipo="lei", numero="11.340", ano=2006),
        devices=[_device()],
        versions=[version or _version()],
    )


def test_build_search_text_includes_context_literal_and_citation() -> None:
    text = build_search_text(
        "Lei nº 11.340/2006 (Lei Maria da Penha)\nArt. 22, caput",
        "proibição de contato com a ofendida",
        "Lei nº 11.340/2006, art. 22, caput, inciso III, alínea b",
    )

    assert text == normalize_search_text(
        "Lei nº 11.340/2006 (Lei Maria da Penha)\nArt. 22, caput\n"
        "proibição de contato com a ofendida\n"
        "Lei nº 11.340/2006, art. 22, caput, inciso III, alínea b"
    )
    assert "artigo 22" in text
    assert "inciso 3" in text
    assert "alinea b" in text
    assert "proibicao de contato" in text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("art. 7º", "artigo 7"),
        ("§ 1º", "paragrafo 1"),
        ("inc. II", "inciso 2"),
        ("al. b", "alinea b"),
        ("24-A", "24-a"),
        ("BO", "boletim de ocorrencia"),
        ("medida de proteção", "medida protetiva"),
    ],
)
def test_build_search_text_applies_docs_05_normalization_table(raw: str, expected: str) -> None:
    assert expected in build_search_text("", raw, "")


def test_content_hash_is_stable_and_sensitive_to_input() -> None:
    metadata = {
        "device_id": "lmp/art7",
        "vigencia_inicio": date(2006, 9, 22),
        "vigencia_fim": None,
        "vigencia_status": "vigente",
    }

    first = content_hash("Texto literal", metadata)
    second = content_hash("Texto literal", metadata)

    assert first == second
    assert first != content_hash("Texto literal alterado", metadata)
    assert first != content_hash("Texto literal", {**metadata, "vigencia_status": "alterado"})


def test_normalize_parse_result_fills_search_text_and_hash() -> None:
    version = _version()
    result = _result(version)

    normalized = normalize_parse_result(result)
    normalized_version = normalized.versions[0]

    assert normalized_version.search_text == build_search_text(
        version.contexto, version.texto_literal, version.citacao
    )
    assert "acao e violencia" in normalized_version.search_text
    assert "ação e violência" not in normalized_version.search_text
    assert normalized_version.texto_literal == version.texto_literal
    assert normalized_version.content_hash != "old"


def test_normalize_parse_result_is_deterministic() -> None:
    first = normalize_parse_result(_result())
    second = normalize_parse_result(_result())

    assert first.versions[0].content_hash == second.versions[0].content_hash
    assert first.versions[0].search_text == second.versions[0].search_text


def test_normalize_parse_result_strips_nr_but_keeps_text_verbatim() -> None:
    version = _version("Texto vigente com continuação (NR).")
    normalized = normalize_parse_result(_result(version)).versions[0]

    assert normalized.texto_literal == "Texto vigente com continuação ."
    assert "(NR)" not in normalized.texto_literal
    assert "(NR)" not in normalized.search_text


def test_struck_text_is_kept_out_of_search_text() -> None:
    parsed = parse_source("lmp", FIXTURE)
    normalized = normalize_parse_result(parsed)

    version = next(v for v in normalized.versions if v.device_id == "lmp/art22/cpt/inc3/ali-b")
    assert version.texto_anterior == "por telefone fixo"
    assert "por telefone fixo" not in version.search_text
    assert "contato com a ofendida" in version.search_text


def test_normalization_does_not_change_literal_from_parser() -> None:
    parsed = parse_source("lmp", FIXTURE)
    normalized = normalize_parse_result(parsed)

    original = {v.device_id: v.texto_literal for v in parsed.versions}
    assert {v.device_id: v.texto_literal for v in normalized.versions} == original
