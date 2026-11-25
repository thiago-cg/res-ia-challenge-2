"""Mapa 3D opcional: só carrega sob demanda, com as bibliotecas no próprio servidor."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "web" / "ui"
MAPA3D = (UI / "scripts" / "mapa3d.js").read_text(encoding="utf-8")
DELEGACIAS = (UI / "scripts" / "delegacias.js").read_text(encoding="utf-8")
HTML = (UI / "index.html").read_text(encoding="utf-8")


def _sem_comentarios(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


def test_bibliotecas_estao_no_repositorio():
    for caminho in (
        "vendor/maplibre/maplibre-gl.js",
        "vendor/maplibre/maplibre-gl.css",
        "vendor/maplibre/LICENSE.txt",
        "vendor/deckgl/deckgl.min.js",
        "vendor/deckgl/LICENSE",
    ):
        assert (UI / caminho).is_file(), caminho


def test_3d_nao_e_carregado_na_abertura():
    # nada de 3D no HTML nem importado de forma estática
    assert "mapa3d" not in HTML
    assert "maplibre" not in HTML.lower()
    assert not re.search(r"^import .*mapa3d", DELEGACIAS, flags=re.M)
    assert 'import("./mapa3d.js")' in DELEGACIAS


def test_unico_terceiro_e_o_provedor_de_blocos():
    codigo = _sem_comentarios(MAPA3D)
    urls = set(re.findall(r'https://[^"\'`\s)<>]+', codigo))
    dominios = {u.split("/")[2] for u in urls}
    assert "tiles.openfreemap.org" in dominios
    permitidos = {
        "tiles.openfreemap.org",
        "openfreemap.org",
        "openmaptiles.org",
        "www.openstreetmap.org",
    }
    assert dominios <= permitidos, dominios - permitidos
    for proibido in ("mapbox.com", "googleapis", "unpkg", "cdn.jsdelivr", "<iframe"):
        assert proibido not in codigo.lower()


def test_aviso_de_privacidade_e_atribuicao():
    assert "OpenFreeMap" in MAPA3D and "OpenStreetMap" in MAPA3D
    assert "data-nota-3d" in DELEGACIAS
    assert "Sua posição não é enviada" in DELEGACIAS


def test_sem_webgl_o_2d_continua():
    assert "temWebGL" in MAPA3D
    assert "temWebGL()" in DELEGACIAS


def test_mesma_interface_do_mapa_2d():
    for nome in ("destruir", "marcarVoce", "focar"):
        assert nome in MAPA3D


def test_respeita_movimento_reduzido():
    assert "prefers-reduced-motion" in MAPA3D
