from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.models import ParseError, ParseResult
from src.ingest.parse_cnj import parse_cnj

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cnj_rc_5_2020.html"


@pytest.fixture(scope="module")
def result() -> ParseResult:
    return parse_cnj("cnj-rc-5-2020", FIXTURE)


def test_norm_metadata(result: ParseResult) -> None:
    assert result.norm.id == "cnj-rc-5-2020"
    assert result.norm.tipo == "resolucao_conjunta"
    assert result.norm.numero == "5"
    assert result.norm.ano == 2020
    assert result.norm.fonte_url == "https://atos.cnj.jus.br/atos/detalhar/3218"


def test_articles_are_numbered_as_devices(result: ParseResult) -> None:
    article_ids = [device.id for device in result.devices if device.tipo == "artigo"]

    assert article_ids == [
        "cnj-rc-5-2020/art1",
        "cnj-rc-5-2020/art2",
        "cnj-rc-5-2020/art3",
        "cnj-rc-5-2020/art4",
    ]
    articles = [device for device in result.devices if device.tipo == "artigo"]
    assert all(device.artigo_id == device.id for device in articles)


def test_article_one_text_and_citation(result: ParseResult) -> None:
    version = next(v for v in result.versions if v.device_id == "cnj-rc-5-2020/art1")

    assert version.texto_literal == (
        "Fica instituído o Formulário Nacional de Avaliação de Risco, nos termos desta Resolução."
    )
    assert version.citacao == "Resolução Conjunta CNJ/CNMP nº 5/2020, art. 1º"
    assert version.vigencia_status == "vigente"
    assert version.vigencia_fim is None
    assert "Resolução Conjunta CNJ/CNMP nº 5/2020" in version.contexto


def test_article_four_citation_and_redacao_note(result: ParseResult) -> None:
    version = next(v for v in result.versions if v.device_id == "cnj-rc-5-2020/art4")

    assert version.texto_literal == ("Esta Resolução entra em vigor na data de sua publicação.")
    assert "(Redação dada" not in version.texto_literal
    assert version.citacao == "Resolução Conjunta CNJ/CNMP nº 5/2020, art. 4º"
    assert version.redacao_dada_por == "Redação dada pela Portaria Conjunta nº 6, de 2025"
    assert version.vigencia_status == "alterado"


def test_malformed_input_raises_parse_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.html"
    empty.write_text("<html><body><p>Sem artigos</p></body></html>", encoding="utf-8")

    with pytest.raises(ParseError):
        parse_cnj("cnj-rc-5-2020", empty)
