"""Centro de bairros/setores do DF (Samambaia Norte, Guará II...) pelo OpenStreetMap.

Precisa de internet e deve ser rodado por uma pessoa, que confere o resultado no mapa:

    uv run python scripts/centros_localidades.py               # só mostra o que achou
    uv run python scripts/centros_localidades.py --gravar      # acrescenta ao localidades_br.csv

Para cada nome, pergunta ao Nominatim (1 consulta por segundo, como pede a política de uso)
e só aceita um ponto que caia dentro do DF e seja um lugar (bairro, setor, região). O que não
for achado ou parecer fora do lugar é listado para você completar à mão. Nomes que já estão
no CSV não são repetidos. Dados © contribuidores do OpenStreetMap (ODbL).
"""

from __future__ import annotations

import argparse
import csv
import time
from collections.abc import Callable
from pathlib import Path

NOMES = (
    "Samambaia Norte",
    "Samambaia Sul",
    "Guará I",
    "Guará II",
    "Ceilândia Norte",
    "Ceilândia Sul",
)
CSV = Path(__file__).resolve().parents[1] / "data" / "seed" / "localidades_br.csv"
USER_AGENT = "zelia-centros-localidades/1.0 (projeto academico; uso unico)"
DF_LAT = (-16.1, -15.4)
DF_LON = (-48.3, -47.3)
CLASSES_DE_LUGAR = {"place", "boundary"}

Busca = Callable[[str], list[dict]]


def escolher(resultados: list[dict]) -> tuple[float, float] | None:
    """Primeiro resultado que é um lugar e fica dentro do DF."""
    for item in resultados:
        if item.get("category", item.get("class")) not in CLASSES_DE_LUGAR:
            continue
        lat, lon = float(item["lat"]), float(item["lon"])
        if DF_LAT[0] < lat < DF_LAT[1] and DF_LON[0] < lon < DF_LON[1]:
            return lat, lon
    return None


def nominatim(consulta: str) -> list[dict]:
    import httpx

    resposta = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": consulta, "format": "jsonv2", "limit": 5, "countrycodes": "br"},
        headers={"User-Agent": USER_AGENT},
        timeout=20.0,
    )
    resposta.raise_for_status()
    return resposta.json()


def achar_centros(
    nomes: tuple[str, ...], buscar: Busca = nominatim, pausa: float = 1.0
) -> tuple[dict[str, tuple[float, float]], list[str]]:
    achados: dict[str, tuple[float, float]] = {}
    faltando: list[str] = []
    for nome in nomes:
        ponto = escolher(buscar(f"{nome}, Brasília, Distrito Federal, Brasil"))
        if ponto:
            achados[nome] = ponto
        else:
            faltando.append(nome)
        time.sleep(pausa)
    return achados, faltando


def acrescentar(caminho: Path, achados: dict[str, tuple[float, float]]) -> list[str]:
    with caminho.open(encoding="utf-8", newline="") as handle:
        existentes = {linha["nome"] for linha in csv.DictReader(handle) if linha["uf"] == "DF"}
    novas = [(n, p) for n, p in achados.items() if n not in existentes]
    with caminho.open("a", encoding="utf-8", newline="") as handle:
        escritor = csv.writer(handle, lineterminator="\n")
        for nome, (lat, lon) in novas:
            escritor.writerow(["DF", nome, "Brasília", f"{lat:.4f}", f"{lon:.4f}"])
    return [n for n, _ in novas]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gravar", action="store_true", help="acrescenta ao localidades_br.csv")
    args = parser.parse_args()
    achados, faltando = achar_centros(NOMES)
    for nome, (lat, lon) in achados.items():
        print(
            f"{nome}: {lat:.4f},{lon:.4f}  https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        )
    for nome in faltando:
        print(f"REVISAR (não achado): {nome}")
    if args.gravar:
        print("gravadas:", ", ".join(acrescentar(CSV, achados)) or "nenhuma (já existiam)")
    else:
        print("\nConfira os links acima e rode de novo com --gravar.")


if __name__ == "__main__":
    main()
