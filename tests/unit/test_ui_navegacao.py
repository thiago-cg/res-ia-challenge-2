"""Organização do menu, da tela principal e do botão de pânico no front."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "web" / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
APP_JS = (UI / "scripts" / "app.js").read_text(encoding="utf-8")
PANICO_JS = (UI / "scripts" / "panico.js").read_text(encoding="utf-8")
CSS = (UI / "styles" / "app.css").read_text(encoding="utf-8")


def _topo() -> str:
    return HTML.split('class="topo__acoes"', 1)[1].split("</header>", 1)[0]


def _menu() -> str:
    return HTML.split('id="contexto"', 1)[1].split("</aside>", 1)[0]


def test_topo_so_tem_sos_e_menu():
    topo = _topo()
    assert 'id="abrir-panico"' in topo
    assert 'id="abrir-contexto"' in topo
    for removido in ("abrir-privacidade", "abrir-fontes", "abrir-delegacias"):
        assert f'id="{removido}"' not in topo


def test_botao_do_menu_aparece_em_qualquer_largura():
    botao = re.search(r'<button[^>]*id="abrir-contexto"[^>]*>', HTML).group(0)
    assert "apenas-mobile" not in botao


def test_menu_tem_privacidade_e_fontes():
    menu = _menu()
    assert 'id="abrir-privacidade"' in menu
    assert 'id="abrir-fontes"' in menu


def test_menu_nao_tem_delegacias_nem_data_do_fato():
    menu = _menu()
    for proibido in ("delegacias", "Data do fato", "data-fato", "limpar-data"):
        assert proibido.lower() not in menu.lower(), proibido


def test_delegacias_ficam_na_tela_principal():
    assert "data-abrir-delegacias" in APP_JS
    atalho = re.search(r"<button[^>]*data-abrir-delegacias[^>]*>", APP_JS).group(0)
    assert "apenas-mobile" not in atalho


def test_privacidade_tem_permissao_de_localizacao():
    dlg = HTML.split('id="dialogo-privacidade"', 1)[1].split("</dialog>", 1)[0]
    assert "Permissão de localização" in dlg
    for ident in ("localizacao-estado", "localizacao-pedir", "localizacao-nota"):
        assert f'id="{ident}"' in dlg
    assert "criarPermissaoLocalizacao" in APP_JS


def test_app_nao_referencia_elementos_removidos():
    for ident in (
        "abrir-privacidade-2",
        "abrir-fontes-2",
        "resumo-privacidade",
        "abrir-delegacias-2",
        "data-fato",
        "limpar-data",
    ):
        assert f'getElementById("{ident}")' not in APP_JS
    assert 'getElementById("abrir-delegacias")' not in APP_JS


def test_panico_tem_190_saida_microfone_e_espaco_para_audios():
    dlg = HTML.split('id="dialogo-panico"', 1)[1].split("</dialog>", 1)[0]
    assert 'href="tel:190"' in dlg
    assert 'id="panico-sair"' in dlg
    assert 'id="panico-mic"' in dlg
    assert "aria-pressed" in dlg
    assert re.search(r'id="panico-audios"[^>]*hidden', dlg)


def test_contrato_do_audio_para_a_outra_equipe():
    assert 'EVENTO_AUDIO = "zelia:panico:audio"' in PANICO_JS
    assert "assumir" in PANICO_JS and "aoTerminar" in PANICO_JS
    readme = (UI / "README.md").read_text(encoding="utf-8")
    assert "zelia:panico:audio" in readme


def test_menu_e_gaveta_em_qualquer_largura():
    bloco = re.search(r"\n\.contexto \{.*?\n\}", CSS, flags=re.S).group(0)
    assert "position: fixed" in bloco


def test_panico_usa_cor_propria():
    tokens = (UI / "styles" / "tokens.css").read_text(encoding="utf-8")
    assert "--cor-panico:" in tokens
