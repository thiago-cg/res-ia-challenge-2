from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.models import ParseError, ParseResult
from src.ingest.parse_sumulas import parse_sumulas

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sumulas_542_600.txt"


@pytest.fixture(scope="module")
def result() -> ParseResult:
    return parse_sumulas("stj-sumulas", FIXTURE)


def test_norm_metadata(result: ParseResult) -> None:
    assert result.norm.id == "stj-sumulas"
    assert result.norm.tipo == "sumula"
    assert result.norm.apelido == "Súmulas do STJ"
    assert result.norm.fonte_url == "https://scon.stj.jus.br/SCON/sumstj/"


def test_one_device_per_enunciado(result: ParseResult) -> None:
    assert [device.id for device in result.devices] == ["stj-sum-542", "stj-sum-600"]
    assert all(device.tipo == "artigo" for device in result.devices)
    assert all(device.norm_id == "stj-sumulas" for device in result.devices)
    assert all(device.parent_id is None for device in result.devices)


def test_sumula_542_text_and_citation(result: ParseResult) -> None:
    version = next(v for v in result.versions if v.device_id == "stj-sum-542")

    assert version.texto_literal == ("Enunciado sintético da Súmula 542 sobre lesão corporal.")
    assert version.citacao == "Súmula nº 542 do STJ"
    assert version.vigencia_status == "vigente"
    assert version.vigencia_fim is None
    assert "Súmulas do STJ" in version.contexto
    assert "Súmula nº 542" in version.contexto


def test_sumula_600_text_and_citation(result: ParseResult) -> None:
    version = next(v for v in result.versions if v.device_id == "stj-sum-600")

    assert version.texto_literal == (
        "Enunciado sintético da Súmula 600 sobre a dispensa de coabitação."
    )
    assert version.citacao == "Súmula nº 600 do STJ"
    assert version.vigencia_status == "vigente"


def test_cancelled_sumula_is_marked_cancelado(tmp_path: Path) -> None:
    path = tmp_path / "sumulas.txt"
    path.write_text(
        "Súmula 601\nEnunciado sintético cancelado.\n(Cancelada)\n",
        encoding="utf-8",
    )

    result = parse_sumulas("stj-sumulas", path)
    version = result.versions[0]

    assert version.device_id == "stj-sum-601"
    assert version.vigencia_status == "cancelado"
    assert version.vigencia_fim is not None
    assert "(Cancelada)" not in version.texto_literal


def test_malformed_input_raises_parse_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("texto sem enunciados\n", encoding="utf-8")

    with pytest.raises(ParseError):
        parse_sumulas("stj-sumulas", empty)
