"""Guarda o kit de marca v1.0 no código: paleta, vetores e proporção.

O manual proíbe distorcer a marca. Um `width`/`height` fixo no HTML distorce em
silêncio quando o SVG muda de `viewBox` — foi exatamente o que aconteceu ao trocar
o retraçado antigo pelos vetores oficiais. Estes testes falham se isso voltar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "web" / "ui" / "assets" / "brand"
SITE_BRAND = ROOT / "site" / "assets" / "brand"
TOKENS = ROOT / "web" / "ui" / "styles" / "tokens.css"
INDEX = ROOT / "web" / "ui" / "index.html"
APP_JS = ROOT / "web" / "ui" / "scripts" / "app.js"
SITE_INDEX = ROOT / "site" / "index.html"

#: Paleta oficial do manual (página 08 · cor).
PALETA = {
    "azul pulso": "#2457d6",
    "verde folha": "#2e8b72",
    "sol": "#f3b83f",
    "aveia": "#f5f0e7",
    "tinta": "#1e2a3a",
}

#: Traço do símbolo oficial (kit v1.0), compartilhado por SVG, HTML e JS.
TRACO_OFICIAL = "M22 36Q55 28 88 33Q104 35 96 47L28 83Q20 95 36 97Q69 102 102 94"
VIEWBOX_SIMBOLO = "0 0 128 128"


def _ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


def test_tokens_expressam_a_paleta_do_manual() -> None:
    tokens = _ler(TOKENS).lower()
    for nome, hexa in PALETA.items():
        assert hexa in tokens, f"{nome} ({hexa}) não aparece em tokens.css"


@pytest.mark.parametrize(
    "arquivo",
    [
        "simbolo-azul.svg",
        "simbolo-branco.svg",
        "wordmark-azul.svg",
        "wordmark-branco.svg",
        "wordmark-tinta.svg",
        "icone-app.svg",
        "favicon.svg",
    ],
)
def test_assets_de_marca_existem_no_ui_e_no_site(arquivo: str) -> None:
    assert (BRAND / arquivo).is_file(), arquivo
    assert (SITE_BRAND / arquivo).is_file(), arquivo


def test_simbolo_carrega_o_traco_oficial() -> None:
    for arquivo in ("simbolo-azul.svg", "simbolo-branco.svg"):
        svg = _ler(BRAND / arquivo)
        assert TRACO_OFICIAL in svg, arquivo
        assert VIEWBOX_SIMBOLO in svg, arquivo
        assert 'stroke-width="18"' in svg, arquivo


def test_wordmark_tem_o_ponto_solar_no_lugar_do_i() -> None:
    svg = _ler(BRAND / "wordmark-azul.svg")
    assert "0 0 230 100" in svg
    assert '<circle cx="159" cy="27" r="8" fill="#F3B83F"/>' in svg


def test_favicon_e_o_mesmo_desenho_do_icone_do_app() -> None:
    assert _ler(BRAND / "favicon.svg") == _ler(BRAND / "icone-app.svg")


def test_simbolo_no_markup_nao_usa_o_retracado_antigo() -> None:
    html = _ler(INDEX)
    js = _ler(APP_JS)
    for fonte, nome in ((html, "index.html"), (js, "app.js")):
        assert TRACO_OFICIAL in fonte, nome
        assert VIEWBOX_SIMBOLO in fonte, nome
        assert "177.379" not in fonte, f"{nome} ainda usa o viewBox do retraçado"
        assert "C 252.424" not in fonte, f"{nome} ainda usa o traço do retraçado"


def _proporcao_do_svg(caminho: Path) -> float:
    match = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', _ler(caminho))
    assert match is not None, caminho
    largura, altura = float(match.group(1)), float(match.group(2))
    return largura / altura


@pytest.mark.parametrize(
    ("pagina", "atributo_largura", "atributo_altura", "arquivo"),
    [
        (INDEX, 230, 100, "wordmark-azul.svg"),
        (SITE_INDEX, 96, 42, "wordmark-azul.svg"),
        (SITE_INDEX, 132, 57, "wordmark-branco.svg"),
    ],
)
def test_wordmark_mantem_proporcao_no_html(
    pagina: Path, atributo_largura: int, atributo_altura: int, arquivo: str
) -> None:
    html = _ler(pagina)
    esperado = f'src="assets/brand/{arquivo}"'
    assert esperado in html
    alvo = re.search(
        r'width="(\d+)" height="(\d+)"',
        html[html.index(esperado) : html.index(esperado) + 160],
    )
    assert alvo is not None
    assert (int(alvo.group(1)), int(alvo.group(2))) == (atributo_largura, atributo_altura)
    real = _proporcao_do_svg(BRAND / arquivo)
    declarada = atributo_largura / atributo_altura
    assert abs(real - declarada) / real < 0.02, (
        f"{pagina.name}: proporção {declarada:.3f} difere do SVG {real:.3f}"
    )
