"""Guarda a promessa de privacidade do painel de delegacias (web/ui).

O painel precisa continuar sem tiles/mapas de terceiros, usar POST (nunca query
string) para a localização e não persistir a posição no navegador.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "web" / "ui"
JS = (UI / "scripts" / "delegacias.js").read_text(encoding="utf-8")
API = (UI / "scripts" / "api.js").read_text(encoding="utf-8")
HTML = (UI / "index.html").read_text(encoding="utf-8")


def test_painel_esta_ligado_no_html():
    for ident in (
        "dialogo-delegacias",
        "abrir-delegacias",
        "deleg-usar-local",
        "deleg-form-cidade",
        "deleg-sair",
    ):
        assert f'id="{ident}"' in HTML


def test_sem_mapa_de_terceiros():
    codigo = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
    for proibido in ("leaflet", "tile.openstreetmap", "mapbox", "maps.googleapis", "<iframe"):
        assert proibido not in codigo.lower()
    assert "<script" not in HTML.lower().replace('<script type="module" src="scripts/app.js">', "")


def test_localizacao_nao_e_persistida():
    codigo = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
    for armazenamento in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert armazenamento not in codigo
    assert "history.pushState" not in codigo and "location.search" not in codigo


def test_localizacao_vai_por_post_e_arredondada():
    assert "/services/nearby" in API
    trecho = API.split("servicosProximos", 1)[1]
    assert 'method: "POST"' in trecho
    assert "arredondarCoordenada" in JS and "* 1000) / 1000" in JS


def test_como_chegar_leva_so_o_destino():
    # O link externo é montado só com dados da delegacia, nunca com a posição da usuária.
    corpo = JS.split("export function linkComoChegar", 1)[1].split("}\n", 1)[0]
    assert "servico." in corpo
    assert "origem" not in corpo and "lat" not in corpo.replace("latitude", "")
