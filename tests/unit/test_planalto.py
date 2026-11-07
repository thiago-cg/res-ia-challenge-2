from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.ingest.models import SOURCE_NORMS, ParseError, ParseResult
from src.ingest.parse_planalto import parse_source

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lmp_art22.html"


@pytest.fixture(scope="module")
def result() -> ParseResult:
    return parse_source("lmp", FIXTURE)


def device_by_id(result: ParseResult, device_id: str):
    matches = [device for device in result.devices if device.id == device_id]
    assert matches, f"missing device {device_id}"
    return matches[0]


def version_by_id(result: ParseResult, device_id: str):
    matches = [version for version in result.versions if version.device_id == device_id]
    assert matches, f"missing version for {device_id}"
    return matches[0]


def test_norm_metadata(result: ParseResult) -> None:
    assert result.norm.id == "lmp"
    assert result.norm.tipo == "lei"
    assert result.norm.numero == "11.340"
    assert result.norm.ano == 2006
    assert result.norm.apelido == "Lei Maria da Penha"
    assert result.norm.urn_lexml == "urn:lex:br:federal:lei:2006-08-07;11340"
    assert result.norm.fonte_url.endswith("/l11340.htm")


def test_article_count(result: ParseResult) -> None:
    articles = [device for device in result.devices if device.tipo == "artigo"]
    assert len(articles) == 3


def test_alinea_b_literal_context_and_citation(result: ParseResult) -> None:
    device = device_by_id(result, "lmp/art22/cpt/inc3/ali-b")
    version = version_by_id(result, "lmp/art22/cpt/inc3/ali-b")

    assert device.tipo == "alinea"
    assert device.rotulo == 'alínea "b"'
    assert version.texto_literal == (
        "contato com a ofendida, seus familiares e testemunhas por qualquer meio de comunicação;"
    )
    assert version.texto_anterior == "por telefone fixo"
    assert version.redacao_dada_por == "Redação dada pela Lei nº 14.550, de 2023"
    assert version.vigencia_status == "alterado"
    assert version.vigencia_fim is None

    assert "por telefone fixo" not in version.texto_literal
    assert "Lei nº 11.340/2006 (Lei Maria da Penha)" in version.contexto
    assert "Título III — Das Medidas Protetivas de Urgência" in version.contexto
    assert "Capítulo II — Das Medidas Protetivas de Urgência que Obrigam o Agressor" in (
        version.contexto
    )
    assert 'Art. 22, caput, inciso III, alínea "b"' in version.contexto

    assert version.citacao == (
        'Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III, alínea "b"'
    )
    assert device.caminho.endswith("Art. 22 > III > b")


def test_parent_chain(result: ParseResult) -> None:
    alinea = device_by_id(result, "lmp/art22/cpt/inc3/ali-b")
    inciso = device_by_id(result, "lmp/art22/cpt/inc3")
    caput = device_by_id(result, "lmp/art22/cpt")
    artigo = device_by_id(result, "lmp/art22")

    assert alinea.parent_id == inciso.id
    assert inciso.parent_id == caput.id
    assert caput.parent_id == artigo.id
    assert artigo.parent_id is None
    assert alinea.artigo_id == artigo.id
    assert inciso.artigo_id == artigo.id
    assert caput.artigo_id == artigo.id


def test_article_caput_and_inciso_content(result: ParseResult) -> None:
    # Intentional: the article-level literal mirrors the caput. Combining
    # caput + incisos into the article chunk is IDX-01's job, not the parser's.
    artigo = version_by_id(result, "lmp/art22")
    caput = version_by_id(result, "lmp/art22/cpt")
    inciso = version_by_id(result, "lmp/art22/cpt/inc3")

    assert artigo.texto_literal.startswith("Constatada a prática de violência doméstica")
    assert caput.texto_literal == artigo.texto_literal
    assert inciso.texto_literal == "proibição de determinadas condutas, entre as quais:"
    assert inciso.citacao == ("Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III")


def test_hyphenated_article_and_strike_forms(result: ParseResult) -> None:
    device = device_by_id(result, "lmp/art24-a")
    version = version_by_id(result, "lmp/art24-a")

    assert device.rotulo == "Art. 24-A"
    assert "pena de detenção de 3 meses a 2 anos" not in version.texto_literal
    assert version.texto_anterior == "pena de detenção de 3 meses a 2 anos"
    assert version.texto_literal == (
        "Descumprimento de medida protetiva: pena de reclusão de 2 a 5 anos."
    )
    assert version.vigencia_status == "alterado"
    assert version.citacao == "Lei nº 11.340/2006 (Lei Maria da Penha), art. 24-A"


def test_tilde_strike_and_nr_are_not_indexed(result: ParseResult) -> None:
    version = version_by_id(result, "lmp/art24-b")

    assert "trecho riscado" not in version.texto_literal
    assert "(NR)" not in version.texto_literal
    assert version.texto_anterior == "trecho riscado"
    assert version.texto_literal == "Texto vigente com continuação."


def test_paragraph_edge_cases(result: ParseResult) -> None:
    par1 = device_by_id(result, "lmp/art24-b/par1")
    par_unico = device_by_id(result, "lmp/art24-b/par-unico")

    assert par1.parent_id == "lmp/art24-b"
    assert par1.rotulo == "§ 1º"
    assert version_by_id(result, "lmp/art24-b/par1").citacao == (
        "Lei nº 11.340/2006 (Lei Maria da Penha), art. 24-B, § 1º"
    )

    assert par_unico.rotulo == "Parágrafo único"
    assert version_by_id(result, "lmp/art24-b/par-unico").citacao == (
        "Lei nº 11.340/2006 (Lei Maria da Penha), art. 24-B, parágrafo único"
    )


def test_vigencia_and_hash_are_deterministic() -> None:
    first = parse_source("lmp", FIXTURE, hoje=date(2026, 11, 5))
    second = parse_source("lmp", FIXTURE, hoje=date(2030, 1, 1))

    assert first.versions == second.versions

    version = version_by_id(first, "lmp/art22/cpt/inc3/ali-b")
    # The amendment is from 2023; the parser must not keep 2006 as the start.
    assert version.vigencia_inicio == date(2023, 12, 31)
    assert version.vigencia_inicio.year == 2023
    assert any("only a year" in warning and "2023" in warning for warning in first.warnings)
    assert version.content_hash == version_by_id(second, "lmp/art22/cpt/inc3/ali-b").content_hash
    assert (
        version.qdrant_point_id == version_by_id(second, "lmp/art22/cpt/inc3/ali-b").qdrant_point_id
    )


def test_placeholder_vigencias_never_precede_publication_year_end() -> None:
    for source_id, meta in SOURCE_NORMS.items():
        if meta.ano is not None and not meta.data_exata:
            assert meta.vigencia_inicio >= date(meta.ano, 12, 31), source_id


def test_revocation_never_uses_parse_time(tmp_path: Path) -> None:
    path = tmp_path / "revogado.html"
    path.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Lei nº 11.340/2006 (Lei Maria da Penha)</title></head><body>"
        "<p>Art. 1º Texto revogado com ano. (Revogado pela Lei nº 2, de 2019)</p>"
        "<p>Art. 2º Texto revogado sem data. (Revogado)</p>"
        "</body></html>",
        encoding="utf-8",
    )

    first = parse_source("lmp", path, hoje=date(2020, 1, 1))
    second = parse_source("lmp", path, hoje=date(2030, 6, 30))

    assert first.versions == second.versions
    assert [v.content_hash for v in first.versions] == [v.content_hash for v in second.versions]

    with_year = version_by_id(first, "lmp/art1")
    assert with_year.vigencia_status == "revogado"
    assert with_year.vigencia_fim == date(2019, 12, 31)

    without_date = version_by_id(first, "lmp/art2")
    assert without_date.vigencia_status == "revogado"
    assert without_date.vigencia_fim is None


def test_annotation_full_date_is_used(tmp_path: Path) -> None:
    path = tmp_path / "full_date.html"
    path.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Lei nº 11.340/2006 (Lei Maria da Penha)</title></head><body>"
        "<p>Art. 1º Texto alterado. "
        "(Redação dada pela Lei nº 2, de 10 de janeiro de 2023)</p>"
        "</body></html>",
        encoding="utf-8",
    )

    result = parse_source("lmp", path, hoje=date(2030, 1, 1))
    version = version_by_id(result, "lmp/art1")

    assert version.vigencia_inicio == date(2023, 1, 10)
    assert not any("only a year" in warning for warning in result.warnings)


def test_vide_annotations_are_kept_as_remissoes(result: ParseResult) -> None:
    assert "Vide ADI 4424" in result.remissoes


def test_malformed_input_raises_parse_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.html"
    empty.write_text("<html><body><p>Sem artigos</p></body></html>", encoding="utf-8")

    with pytest.raises(ParseError, match="article"):
        parse_source("lmp", empty)


def test_new_laws_use_the_official_vigencia_start_date() -> None:
    from src.ingest.models import default_vigencia_inicio

    assert default_vigencia_inicio("lei-15438-2026") == date(2026, 6, 19)
    assert default_vigencia_inicio("lei-14994-2024") == date(2024, 10, 10)


def test_annotation_resolves_known_law_vigencia_start_date() -> None:
    from src.ingest.parse_planalto import resolve_annotation_date

    assert resolve_annotation_date("Incluido pela Lei n 15.438, de 2026") == (
        date(2026, 6, 19),
        True,
    )
