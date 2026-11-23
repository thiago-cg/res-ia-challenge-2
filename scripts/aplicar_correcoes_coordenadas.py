"""Aplica data/seed/correcoes_coordenadas_df.csv aos seeds de delegacias do DF.

Origem das correções: ``scripts/verificar_coordenadas.py`` (relatório de 23/11/2026).
Entram só pontos com confiança alta (2+ fontes de acordo, marcados como verificados) e pontos
de uma delegacia mapeada no OpenStreetMap (continuam como "Localização aproximada").
Pontos vindos só de CEP ficam de fora: o CEP da região inteira cai no mesmo lugar.

    uv run python scripts/aplicar_correcoes_coordenadas.py          # mostra o que mudaria
    uv run python scripts/aplicar_correcoes_coordenadas.py --gravar # grava nos seeds

Casa as linhas pelo nome; pode rodar mais de uma vez.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"
CORRECOES = SEED / "correcoes_coordenadas_df.csv"
ALVOS = ("services_df.csv", "services_df_pcdf.csv", "services_df_pcdf.geocodificado.csv")


def ler_correcoes(caminho: Path = CORRECOES) -> dict[str, dict[str, str]]:
    with caminho.open(newline="", encoding="utf-8") as handle:
        return {linha["nome"]: linha for linha in csv.DictReader(handle)}


def aplicar(caminho: Path, correcoes: dict[str, dict[str, str]], gravar: bool) -> list[str]:
    with caminho.open(newline="", encoding="utf-8") as handle:
        leitor = csv.DictReader(handle)
        campos = leitor.fieldnames or []
        linhas = list(leitor)
    mudancas = []
    for linha in linhas:
        nova = correcoes.get(linha["nome"])
        if not nova:
            continue
        antes = (linha["latitude"], linha["longitude"], linha["coordenada_verificada"])
        linha["latitude"] = nova["latitude"]
        linha["longitude"] = nova["longitude"]
        linha["coordenada_verificada"] = nova["coordenada_verificada"]
        if antes != (linha["latitude"], linha["longitude"], linha["coordenada_verificada"]):
            mudancas.append(
                f"{caminho.name}: {linha['nome']}  {antes[0]},{antes[1]} -> "
                f"{linha['latitude']},{linha['longitude']}"
            )
    if gravar and mudancas:
        with caminho.open("w", newline="", encoding="utf-8") as handle:
            escritor = csv.DictWriter(handle, fieldnames=campos, lineterminator="\n")
            escritor.writeheader()
            escritor.writerows(linhas)
    return mudancas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gravar", action="store_true", help="grava nos seeds (padrão: só mostra)")
    args = parser.parse_args()
    correcoes = ler_correcoes()
    total = 0
    for nome in ALVOS:
        caminho = SEED / nome
        if not caminho.exists():
            continue
        mudancas = aplicar(caminho, correcoes, args.gravar)
        total += len(mudancas)
        print("\n".join(mudancas))
    print(f"\n{total} linha(s) {'gravada(s)' if args.gravar else 'a mudar (use --gravar)'}.")


if __name__ == "__main__":
    main()
