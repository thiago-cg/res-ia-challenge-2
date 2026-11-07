from __future__ import annotations

from datetime import date
from uuid import NAMESPACE_URL, uuid5

from src.contracts import Device, DeviceVersion
from src.ingest.models import Norm, ParseResult
from src.ingest.normalize import normalize_parse_result
from src.ingest.validate import validate_parse_result


def _device(device_id: str, *, tipo: str = "artigo", parent: str | None = None) -> Device:
    return Device(
        id=device_id,
        norm_id="lmp",
        parent_id=parent,
        artigo_id="lmp/art1",
        tipo=tipo,  # type: ignore[arg-type]
        rotulo=device_id,
        caminho=device_id,
        ordem=1,
    )


def _version(
    device_id: str,
    *,
    literal: str = "Texto vigente.",
    anterior: str | None = None,
    contexto: str = "Lei nÂº 11.340/2006",
    citacao: str = "Lei nÂº 11.340/2006, art. 1Âº",
    status: str = "vigente",
    fim: date | None = None,
) -> DeviceVersion:
    return DeviceVersion(
        device_id=device_id,
        norm_version_id=1,
        texto_literal=literal,
        texto_anterior=anterior,
        contexto=contexto,
        citacao=citacao,
        vigencia_status=status,  # type: ignore[arg-type]
        redacao_dada_por=None,
        vigencia_inicio=date(2006, 9, 22),
        vigencia_fim=fim,
        fonte_url="https://example.test",
        content_hash="placeholder",
        qdrant_point_id=uuid5(NAMESPACE_URL, device_id),
        search_text="",
    )


def _valid_result() -> ParseResult:
    result = ParseResult(
        norm=Norm(id="lmp", tipo="lei", numero="11.340", ano=2006),
        devices=[
            _device("lmp/art1"),
            _device("lmp/art1/cpt", tipo="caput", parent="lmp/art1"),
        ],
        versions=[
            _version("lmp/art1"),
            _version("lmp/art1/cpt"),
        ],
    )
    return normalize_parse_result(result)


def test_valid_result_has_no_errors() -> None:
    report = validate_parse_result(_valid_result(), expected_article_count=1, sample_checked=True)

    assert report.errors == []
    assert report.ok
    assert report.sample_check is True


def test_leaf_without_parent_is_an_error() -> None:
    result = _valid_result()
    result.devices.append(_device("lmp/art1/cpt/inc1", tipo="inciso"))
    result.versions.append(_version("lmp/art1/cpt/inc1"))

    report = validate_parse_result(normalize_parse_result(result))

    assert any("parent" in error and "lmp/art1/cpt/inc1" in error for error in report.errors)


def test_artigo_id_must_exist_as_device() -> None:
    result = _valid_result()
    result.devices[1] = result.devices[1].model_copy(update={"artigo_id": "lmp/missing"})

    report = validate_parse_result(normalize_parse_result(result))

    assert any("artigo_id" in error for error in report.errors)


def test_empty_literal_is_an_error() -> None:
    result = _valid_result()
    result.versions[0] = _version("lmp/art1", literal="   ")

    report = validate_parse_result(normalize_parse_result(result))

    assert any("empty" in error for error in report.errors)


def test_struck_text_in_literal_is_an_error() -> None:
    result = _valid_result()
    result.versions[0] = _version("lmp/art1", literal="pena antiga", anterior="pena antiga")

    report = validate_parse_result(normalize_parse_result(result))

    assert any("struck" in error for error in report.errors)


def test_strike_markup_in_literal_is_an_error() -> None:
    result = _valid_result()
    result.versions[0] = _version("lmp/art1", literal="<s>texto</s> vigente")

    report = validate_parse_result(normalize_parse_result(result))

    assert any("struck" in error for error in report.errors)


def test_vigencia_fim_before_inicio_is_an_error() -> None:
    result = _valid_result()
    result.versions[0] = _version("lmp/art1", fim=date(2005, 1, 1))

    report = validate_parse_result(normalize_parse_result(result))

    assert any("vigencia_fim" in error and "precedes" in error for error in report.errors)


def test_parenthetical_struck_note_does_not_block_validation() -> None:
    result = _valid_result()
    result.versions[0] = _version(
        "lmp/art1",
        literal="Texto vigente. (Regulamento)",
        anterior="(Regulamento)",
    )

    report = validate_parse_result(normalize_parse_result(result))

    assert not any("struck" in error for error in report.errors)


def test_citation_must_be_present() -> None:
    result = _valid_result()
    result.versions[0] = _version("lmp/art1", citacao="")

    report = validate_parse_result(normalize_parse_result(result))

    assert any("citation" in error for error in report.errors)


def test_overlapping_current_versions_are_an_error() -> None:
    result = _valid_result()
    result.versions.append(_version("lmp/art1"))

    report = validate_parse_result(result)

    assert any("overlap" in error for error in report.errors)


def test_device_over_max_length_requires_explicit_split() -> None:
    result = _valid_result()
    result.versions[0] = _version("lmp/art1", literal="x" * 50)

    report = validate_parse_result(normalize_parse_result(result), max_length=40, tokenizer=len)
    assert any("max_length" in error for error in report.errors)

    allowed = validate_parse_result(
        normalize_parse_result(result),
        max_length=40,
        tokenizer=len,
        split_device_ids={"lmp/art1"},
    )
    assert not any("max_length" in error for error in allowed.errors)


def test_context_alone_can_exceed_max_tokens() -> None:
    result = _valid_result()
    result.versions[0] = _version(
        "lmp/art1",
        literal="Texto curto.",
        contexto="contexto longo " * 10,
    )

    report = validate_parse_result(normalize_parse_result(result), max_length=40, tokenizer=len)

    assert any("contexto + texto_literal" in error for error in report.errors)


def test_citation_must_resolve_to_a_norm_in_the_result() -> None:
    result = _valid_result().model_copy(
        update={"norm": Norm(id="outra-norma", tipo="lei", numero="1", ano=2020)}
    )

    report = validate_parse_result(result)

    assert any("citation does not resolve" in error for error in report.errors)


def test_article_count_mismatch_is_an_error() -> None:
    report = validate_parse_result(_valid_result(), expected_article_count=3)

    assert any("article count" in error for error in report.errors)


def test_unstable_hash_is_an_error() -> None:
    result = _valid_result()
    result.versions[0] = result.versions[0].model_copy(update={"content_hash": "tampered"})

    report = validate_parse_result(result)

    assert any("hash" in error for error in report.errors)


def test_sample_check_is_reported_as_warning_when_missing() -> None:
    report = validate_parse_result(_valid_result(), sample_checked=False)

    assert report.sample_check is False
    assert any("sample" in warning for warning in report.warnings)
