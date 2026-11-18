"""Seed das delegacias do DF a partir do levantamento da PCDF (páginas oficiais, 16/11/2026).

Entradas:
  data/seed/pcdf_delegacias_dataset.csv   nome, endereço, CEP e URL oficial de cada DP
  data/seed/services_deam_cnj.raw (CNJ)   só para os TELEFONES, vinculados à DP pelo mapa abaixo

Regras:
- DEAM I e II NÃO entram aqui: já existem curadas em services_df.csv.
- DP sem endereço no levantamento só entra se o CNJ trouxer o endereço dela (``DO_CNJ``).
- A coordenada é a do arquivo (se houver) ou o centro aproximado da região administrativa,
  sempre com ``coordenada_verificada=false``. Para chegar à porta da delegacia, rode
  ``scripts/geocode_services.py`` (precisa de internet) e revise o relatório.

    python scripts/build_pcdf_seed.py --cnj-seed data/seed/services_deam_cnj_df.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services import lugares  # noqa: E402

PCDF_CSV = ROOT / "data" / "seed" / "pcdf_delegacias_dataset.csv"
SAIDA = ROOT / "data" / "seed" / "services_df_pcdf.csv"
ATUALIZADO_EM = "2026-11-16"

#: Telefone (lista do CNJ, 2023) de cada DP. "confere" = endereço igual nas duas fontes;
#: "inferido" = mesma região e mesma unidade, mas o endereço está escrito diferente.
TELEFONE_CNJ: dict[str, tuple[str, str]] = {
    "01": ("(61) 3207-6332", "confere"), "02": ("(61) 3207-6421", "confere"),
    "03": ("(61) 3207-6535", "confere"), "04": ("(61) 3207-6576", "confere"),
    "05": ("(61) 3207-6655", "confere"), "06": ("(61) 3207-6738", "confere"),
    "10": ("(61) 3207-6992", "confere"), "11": ("(61) 3207-7057", "inferido"),
    "12": ("(61) 3207-6066", "confere"), "13": ("(61) 3207-7235", "inferido"),
    "14": ("(61) 3207-7318", "inferido"), "17": ("(61) 3207-7572", "confere"),
    "18": ("(61) 3479-9015", "inferido"), "19": ("(61) 3207-7723", "confere"),
    "20": ("(61) 3207-7821", "confere"), "21": ("(61) 3207-7882", "confere"),
    "23": ("(61) 3207-7960", "confere"), "24": ("(61) 3207-8042", "confere"),
    "26": ("(61) 3207-8132", "confere"), "27": ("(61) 3207-8209", "confere"),
    "29": ("(61) 3207-8280", "confere"), "30": ("(61) 3207-8368", "confere"),
    "31": ("(61) 3207-8419", "confere"), "33": ("(61) 3207-8611", "confere"),
    "35": ("(61) 3207-8673", "inferido"), "38": ("(61) 3207-8763", "confere"),
}  # fmt: skip

#: DPs sem endereço no levantamento da PCDF, preenchidas com o endereço (e telefone) do CNJ.
DO_CNJ: dict[str, tuple[str, str, str]] = {
    "08": ("(61) 3207-6854", "Trecho 2, Lotes 1455/1475 – SIA", "SCIA"),
    "09": ("(61) 3207-6943", "SHIN 3/5 – Lago Norte", "Lago Norte"),
    "32": ("(61) 3207-8498", "QN 308, Conjunto 01, Lote 01 – Samambaia Sul", "Samambaia"),
}  # fmt: skip

#: Região administrativa do levantamento -> lugar da lista local (data/seed/localidades_br.csv)
ALIAS_REGIAO = {
    "cruzeiro velho": "Cruzeiro", "guara ii": "Guará", "scia": "Estrutural",
    "taguatinga norte": "Taguatinga", "taguatinga sul": "Taguatinga",
    "riacho fundo i": "Riacho Fundo",
}  # fmt: skip

CAMPOS = [
    "uf", "municipio", "nome", "tipo", "endereco", "telefone", "horario", "latitude",
    "longitude", "coordenada_verificada", "origem", "fonte_url", "atualizado_em",
]  # fmt: skip


def _numero(nome: str) -> str | None:
    achou = re.match(r"\s*(\d{1,2})\s*ª?\s*DP", nome)
    return achou.group(1).zfill(2) if achou else None


def _sem_acento(texto: str) -> str:
    from src.services.municipios import normalizar

    return normalizar(texto)


def _centro(regiao: str) -> tuple[float, float] | None:
    nome = ALIAS_REGIAO.get(_sem_acento(regiao), regiao)
    lugar = lugares.buscar("DF", nome)
    return (lugar.latitude, lugar.longitude) if lugar else None


def construir(linhas: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    saida: list[dict[str, str]] = []
    revisao: list[str] = []
    for bruta in linhas:
        nome = bruta["nome"].strip()
        numero = _numero(nome)
        if bruta["tipo"].strip() != "circunscricional" or numero is None:
            revisao.append(f"{nome}: fora do seed (DEAM já curada em services_df.csv)")
            continue
        endereco = bruta["endereco"].strip()
        telefone: str | None = TELEFONE_CNJ.get(numero, (None, ""))[0]
        regiao = bruta["regiao_administrativa"].strip()
        if endereco == "Endereço não recuperado":
            extra = DO_CNJ.get(numero)
            if not extra:
                revisao.append(f"{nome}: sem endereço no levantamento nem no CNJ")
                continue
            telefone, endereco, regiao = extra
            revisao.append(f"{nome}: endereço e telefone vieram do CNJ (2023), confirmar")
        cep = bruta["cep"].strip()
        completo = f"{endereco} – {regiao}, Brasília/DF" + (f" – CEP {cep}" if cep else "")
        if bruta["latitude"].strip() and bruta["longitude"].strip():
            lat, lon = float(bruta["latitude"]), float(bruta["longitude"])
        else:
            centro = _centro(regiao)
            if centro is None:
                revisao.append(f"{nome}: região {regiao!r} sem ponto na lista local")
                continue
            lat, lon = centro
        if numero in TELEFONE_CNJ and TELEFONE_CNJ[numero][1] == "inferido":
            revisao.append(
                f"{nome}: telefone vinculado por região/unidade (endereço difere), confirmar"
            )
        if telefone is None:
            revisao.append(f"{nome}: sem telefone (não consta na lista do CNJ)")
        saida.append(
            {
                "uf": "DF",
                "municipio": "Brasília",
                "nome": nome,
                "tipo": "delegacia_comum",
                "endereco": completo,
                "telefone": telefone or "",
                "horario": "",
                "latitude": f"{lat:.5f}",
                "longitude": f"{lon:.5f}",
                "coordenada_verificada": "false",
                "origem": "pcdf",
                "fonte_url": bruta["fonte_oficial"].strip(),
                "atualizado_em": ATUALIZADO_EM,
            }
        )
    return saida, revisao


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entrada", type=Path, default=PCDF_CSV)
    ap.add_argument("--saida", type=Path, default=SAIDA)
    ap.add_argument("--revisao", type=Path, default=SAIDA.with_suffix(".revisao.txt"))
    args = ap.parse_args(argv)
    with args.entrada.open(encoding="utf-8-sig", newline="") as handle:
        linhas, revisao = construir(list(csv.DictReader(handle)))
    with args.saida.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.DictWriter(handle, fieldnames=CAMPOS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(linhas)
    args.revisao.write_text("\n".join(revisao) + "\n", encoding="utf-8")
    print(f"{len(linhas)} DPs no seed, {len(revisao)} observações em {args.revisao.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
