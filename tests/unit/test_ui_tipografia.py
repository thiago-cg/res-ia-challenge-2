"""Tipografia e estrutura da tela: duas famílias, uma só serifada e sem blocos repetidos."""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "web" / "ui"
FONTES = (UI / "styles" / "fonts.css").read_text(encoding="utf-8")
TOKENS = (UI / "styles" / "tokens.css").read_text(encoding="utf-8")
CSS = (UI / "styles" / "app.css").read_text(encoding="utf-8")
HTML = (UI / "index.html").read_text(encoding="utf-8")
APP_JS = (UI / "scripts" / "app.js").read_text(encoding="utf-8")


def test_so_duas_familias_de_fonte_sao_declaradas():
    familias = set(re.findall(r'font-family:\s*"([^"]+)"', FONTES))
    assert familias == {"Afacad Flux", "Newsreader"}


def test_nenhuma_regra_usa_familia_fora_dos_tokens():
    # Toda família vem de --fonte-texto ou --fonte-editorial; nada solto no app.css.
    soltas = [
        linha
        for linha in CSS.splitlines()
        if "font-family:" in linha and "var(--fonte-" not in linha
    ]
    assert soltas == []


def test_campos_de_formulario_herdam_a_fonte_do_site():
    # Sem isso o <select> cai em Arial no navegador.
    regra = re.search(r"button,\s*input,\s*select,\s*textarea\s*\{[^}]*font:\s*inherit", CSS)
    assert regra, "button, input, select e textarea precisam de font: inherit"


def test_serifada_aparece_so_no_destaque_do_titulo():
    usos = re.findall(r"var\(--fonte-editorial\)", CSS)
    assert len(usos) == 1
    assert ".abertura__titulo em" in CSS.split("var(--fonte-editorial)")[0].rsplit("}", 1)[-1]


def test_sem_peso_700_ou_bold():
    assert not re.search(r"font-weight:\s*(700|bold)", CSS)
    assert re.search(r"strong,\s*b\s*\{\s*font-weight:\s*var\(--peso-semi\)", CSS)


def test_lateral_tem_so_os_tres_cartoes_essenciais():
    lateral = HTML.split('<aside class="contexto"')[1].split("</aside>")[0]
    titulos = re.findall(r'<h2 class="contexto__titulo">([^<]+)', lateral)
    assert [t.strip() for t in titulos] == [
        "Data do fato",
        "Delegacias perto de você",
        "Privacidade",
    ]


def test_perguntas_de_exemplo_nao_se_repetem_na_lateral():
    assert "exemplos-lista" not in HTML
    assert "exemplosLista" not in APP_JS
    assert "preencherExemplos" not in APP_JS


def test_status_e_data_da_base_continuam_na_tela():
    # O app.js escreve nesses elementos (selo do topo + rodapé da lateral).
    for ident in ("status-servico", "status-texto", "nota-base"):
        assert f'id="{ident}"' in HTML
        assert f'getElementById("{ident}")' in APP_JS
