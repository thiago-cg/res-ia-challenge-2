"""Pasta segura: marcação, ordem na barra superior e regras de segurança do código."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "web" / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")


def test_botao_da_pasta_fica_a_esquerda_do_sos():
    topo = HTML.split('class="topo__acoes"', 1)[1].split("</header>", 1)[0]
    assert topo.index('id="abrir-cofre"') < topo.index('id="abrir-panico"')
    assert topo.index('id="abrir-panico"') < topo.index('id="abrir-delegacias"')


def test_dialogo_tem_os_quatro_estados_e_campos_de_pin_numericos():
    for estado in ("indisponivel", "novo", "trancado", "aberto"):
        assert f'data-cofre="{estado}"' in HTML
    for campo in ("cofre-novo-pin", "cofre-novo-pin2", "cofre-abrir-pin"):
        tag = re.search(rf'<input[^>]*id="{campo}"[^>]*>', HTML).group(0)
        assert 'type="password"' in tag and 'inputmode="numeric"' in tag
        assert 'autocomplete="off"' in tag


def test_apagar_conversa_oferece_criar_a_pasta():
    assert 'id="apagar-criar-pasta"' in HTML


def test_cripto_usa_parametros_fortes():
    js = (UI / "scripts" / "cofre-cripto.js").read_text(encoding="utf-8")
    assert "ITERACOES_PIN = 600_000" in js
    assert "AES-GCM" in js and "P-256" in js and "SHA-256" in js


def test_nada_vai_para_a_rede_nem_para_localstorage():
    nomes = ("cofre-cripto.js", "cofre.js", "armazem-idb.js", "relatorio.js", "pasta-segura.js")
    for nome in nomes:
        js = (UI / "scripts" / nome).read_text(encoding="utf-8")
        assert "fetch(" not in js and "XMLHttpRequest" not in js and "sendBeacon" not in js, nome
        assert "localStorage" not in js and "sessionStorage" not in js, nome
        assert "innerHTML" not in js, nome
