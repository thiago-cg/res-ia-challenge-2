from __future__ import annotations

from src.contracts import Citation
from src.index.chunk import estimate_tokens
from src.retrieve.render import render_citation, render_context


def citation(
    texto: str = "texto literal",
    citacao: str = "Lei nº 11.340/2006, art. 22",
    *,
    contexto: str = "",
    device_id: str = "lmp/art22",
) -> Citation:
    return Citation(
        device_id=device_id,
        norm_version_id=1,
        citacao=citacao,
        texto=texto,
        contexto=contexto,
        vigencia="vigente",
        fonte_url="https://www.planalto.gov.br",
    )


def test_render_citation_uses_exact_bracket_format() -> None:
    item = citation(
        citacao='Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III, alínea "b"',
        device_id="lmp/art22/cpt/inc3/ali-b",
    )

    assert render_citation(item) == (
        '[Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III, alínea "b"]'
    )


def test_render_citation_does_not_double_wrap() -> None:
    assert render_citation(citation(citacao="[Lei nº 11.340/2006]")) == "[Lei nº 11.340/2006]"


def test_render_context_orders_law_sumula_cnj_then_doctrine() -> None:
    citations = [
        citation("texto de doutrina", "Doutrina sobre medidas protetivas", device_id="doutrina/1"),
        citation(
            "texto cnj",
            "Resolução Conjunta CNJ/CNMP nº 5/2020",
            device_id="cnj/1",
        ),
        citation("texto súmula", "Súmula 542 do STJ", device_id="sumula/542"),
        citation("texto lei", "Lei nº 11.340/2006, art. 22"),
    ]

    rendered = render_context(citations)

    assert rendered.index("[Lei nº 11.340/2006") < rendered.index("[Súmula 542")
    assert rendered.index("[Súmula 542") < rendered.index("[Resolução Conjunta CNJ")
    assert rendered.index("[Resolução Conjunta CNJ") < rendered.index("[Doutrina sobre medidas")


def test_render_context_never_truncates_literal() -> None:
    literal = "palavra " * 500 + "fim literal"
    rendered = render_context([citation(literal)], max_tokens=10)

    assert literal in rendered


def test_render_context_drops_lowest_priority_when_over_budget() -> None:
    law = citation("texto de lei", "Lei nº 11.340/2006, art. 22")
    doctrine_text = "doutrina " * 500
    doctrine = citation(doctrine_text, "Doutrina longa", device_id="doutrina/1")

    rendered = render_context([law, doctrine], max_tokens=100)

    assert "texto de lei" in rendered
    assert doctrine_text not in rendered
    assert estimate_tokens(rendered) <= 100


def test_render_context_caps_explanation_at_200_tokens() -> None:
    explanation = "explicação " * 400
    item = citation("texto curto", contexto=explanation)

    rendered = render_context([item], max_tokens=6000)

    assert explanation not in rendered
    assert "texto curto" in rendered
    assert estimate_tokens(rendered) <= 6000
