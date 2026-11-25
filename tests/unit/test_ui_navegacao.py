"""Organização do menu e do botão de pânico no front."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "web" / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
APP_JS = (UI / "scripts" / "app.js").read_text(encoding="utf-8")


def _topo() -> str:
    return HTML.split('class="topo__acoes"', 1)[1].split("</header>", 1)[0]


def test_topo_nao_tem_delegacias():
    assert 'id="abrir-delegacias"' not in HTML


def test_topo_tem_privacidade_fontes_e_sos():
    topo = _topo()
    for ident in ("abrir-privacidade", "abrir-fontes", "abrir-panico"):
        assert f'id="{ident}"' in topo


def test_lateral_sem_privacidade_nem_fontes():
    lateral = HTML.split('id="contexto"', 1)[1].split("</aside>", 1)[0]
    assert "abrir-privacidade-2" not in lateral
    assert "abrir-fontes-2" not in lateral
    assert "resumo-privacidade" not in lateral
    assert "abrir-delegacias-2" in lateral


def test_panico_tem_190_saida_e_espaco_para_audios():
    dlg = HTML.split('id="dialogo-panico"', 1)[1].split("</dialog>", 1)[0]
    assert 'href="tel:190"' in dlg
    assert 'id="panico-sair"' in dlg
    assert re.search(r'id="panico-audios"[^>]*hidden', dlg)


def test_app_nao_referencia_elementos_removidos():
    for ident in ("abrir-privacidade-2", "abrir-fontes-2", "resumo-privacidade"):
        assert ident not in APP_JS
    assert 'getElementById("abrir-delegacias")' not in APP_JS


def test_panico_usa_cor_propria():
    tokens = (UI / "styles" / "tokens.css").read_text(encoding="utf-8")
    assert "--cor-panico:" in tokens
