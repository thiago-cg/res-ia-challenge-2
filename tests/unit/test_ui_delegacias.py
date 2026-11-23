"""Guarda a promessa de privacidade do painel de delegacias (web/ui).

O painel só pode falar com mapas de terceiros depois de um toque explícito (mapa.js,
carregado sob demanda), usar POST (nunca query string) para a localização e não
persistir a posição no navegador.
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


MAPA = (UI / "scripts" / "mapa.js").read_text(encoding="utf-8")


def test_mapa_de_ruas_so_carrega_sob_demanda():
    codigo = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
    assert not re.search(r"^import .*mapa\.js", codigo, flags=re.M)
    assert 'import("./mapa.js")' in codigo
    assert "data-abrir-mapa" in codigo and "OpenStreetMap" in codigo  # aviso antes do toque
    assert "mapa.js" not in HTML and "leaflet" not in HTML.lower().replace("mapa de ruas", "")


def test_mapa_usa_leaflet_local_e_nao_grava_nem_envia_posicao():
    assert (UI / "vendor" / "leaflet" / "leaflet.js").is_file()
    assert (UI / "vendor" / "leaflet" / "LICENSE").is_file()
    codigo = re.sub(r"/\*.*?\*/", "", MAPA, flags=re.S)
    assert "unpkg" not in codigo and "cdn" not in codigo.lower()
    for armazenamento in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "fetch(",
    ):
        assert armazenamento not in codigo
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in codigo
    assert "no-referrer" in codigo
