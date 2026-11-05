import json

import pytest
from pydantic import ValidationError

from src.generate.schemas import LLMCitation, LLMOutput, LLMOutputError, parse_llm_output


def valid_payload() -> dict:
    return {
        "resposta": "A lei prevê uma medida protetiva.",
        "citacoes": [
            {
                "device_id": "lmp/art22/cpt/inc3/ali-b",
                "afirmacao": "A lei permite afastamento do agressor.",
            }
        ],
        "proximos_passos": ["Procurar a Defensoria Pública."],
        "encaminhamentos": [{"tipo": "defensoria", "descricao": "Orienta o pedido."}],
        "premissas": [],
        "nivel_confianca": "alto",
        "abstencao": False,
        "motivo_abstencao": None,
    }


def test_parse_valid_json() -> None:
    output = parse_llm_output(json.dumps(valid_payload()))

    assert output.nivel_confianca == "alto"
    assert output.citacoes[0].device_id == "lmp/art22/cpt/inc3/ali-b"
    assert output.abstencao is False


def test_parse_markdown_fenced_json() -> None:
    raw = f"```json\n{json.dumps(valid_payload())}\n```"

    output = parse_llm_output(raw)

    assert output.resposta.startswith("A lei")


def test_rejects_citacao_from_llm() -> None:
    payload = valid_payload()
    payload["citacoes"][0]["citacao"] = "Lei nº 11.340/2006, art. 22"

    with pytest.raises(LLMOutputError):
        parse_llm_output(json.dumps(payload))


def test_rejects_norm_version_id_from_llm() -> None:
    payload = valid_payload()
    payload["citacoes"][0]["norm_version_id"] = 42

    with pytest.raises(LLMOutputError):
        parse_llm_output(json.dumps(payload))


def test_rejects_norm_version_id_at_top_level() -> None:
    payload = valid_payload()
    payload["norm_version_id"] = 42

    with pytest.raises(LLMOutputError):
        parse_llm_output(json.dumps(payload))


def test_rejects_missing_required_field() -> None:
    payload = valid_payload()
    del payload["resposta"]

    with pytest.raises(LLMOutputError):
        parse_llm_output(json.dumps(payload))


def test_parses_abstention_payload() -> None:
    payload = {
        "resposta": "Não encontrei base suficiente.",
        "abstencao": True,
        "motivo_abstencao": "fora do corpus",
    }

    output = parse_llm_output(json.dumps(payload))

    assert output.abstencao is True
    assert output.motivo_abstencao == "fora do corpus"
    assert output.citacoes == []


def test_invalid_json_raises_clear_error() -> None:
    with pytest.raises(LLMOutputError, match="JSON"):
        parse_llm_output("not json at all")


def test_invalid_schema_raises_clear_error() -> None:
    payload = valid_payload()
    payload["nivel_confianca"] = "altissimo"

    with pytest.raises(LLMOutputError, match="inválido|schema"):
        parse_llm_output(json.dumps(payload))


def test_llm_citation_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LLMCitation(device_id="x", afirmacao="y", citacao="z")


def test_llm_output_defaults_for_optional_lists() -> None:
    output = LLMOutput(resposta="ok")

    assert output.citacoes == []
    assert output.proximos_passos == []
    assert output.encaminhamentos == []
    assert output.premissas == []
    assert output.abstencao is False
    assert output.motivo_abstencao is None
