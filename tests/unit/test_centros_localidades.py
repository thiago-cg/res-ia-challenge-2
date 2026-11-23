"""Centros de localidades: aceita só lugar dentro do DF e não repete nomes."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "centros_localidades", ROOT / "scripts" / "centros_localidades.py"
)
modulo = importlib.util.module_from_spec(spec)
sys.modules["centros_localidades"] = modulo
spec.loader.exec_module(modulo)


def _item(categoria, lat, lon):
    return {"category": categoria, "lat": str(lat), "lon": str(lon)}


def test_escolher_ignora_o_que_nao_e_lugar_e_o_que_esta_fora_do_df():
    resultados = [
        _item("highway", -15.87, -48.08),  # rua
        _item("place", -23.55, -46.63),  # São Paulo
        _item("place", -15.87, -48.08),  # bairro no DF
    ]
    assert modulo.escolher(resultados) == (-15.87, -48.08)
    assert modulo.escolher([_item("highway", -15.87, -48.08)]) is None


def test_achar_centros_separa_achados_e_faltando():
    respostas = {
        "Guará II, Brasília, Distrito Federal, Brasil": [_item("place", -15.83, -47.98)],
    }
    achados, faltando = modulo.achar_centros(
        ("Guará II", "Guará I"), buscar=lambda q: respostas.get(q, []), pausa=0
    )
    assert achados == {"Guará II": (-15.83, -47.98)}
    assert faltando == ["Guará I"]


def test_acrescentar_nao_repete_nomes_existentes(tmp_path):
    caminho = tmp_path / "localidades.csv"
    caminho.write_text("uf,nome,municipio,latitude,longitude\nDF,Guará II,Brasília,-15.83,-47.98\n")
    novas = modulo.acrescentar(caminho, {"Guará II": (-15.83, -47.98), "Guará I": (-15.82, -47.97)})
    assert novas == ["Guará I"]
    nomes = [linha["nome"] for linha in csv.DictReader(caminho.open(encoding="utf-8"))]
    assert nomes == ["Guará II", "Guará I"]
