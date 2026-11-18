"""Gera linhas de seed das DEAMs a partir da lista do CNJ (2023).

Fonte: "Delegacias Especializadas de Atendimento à Mulher" (CNJ, set/2023), PDF público.
Extrai com ``pdftotext -layout``, valida o município contra o IBGE e posiciona cada
delegacia no CENTRO do município (coordenada aproximada, ``coordenada_verificada=false``).

Linhas sem município identificável ou com município que não existe na UF vão para o
relatório de revisão e NÃO entram no seed: é melhor faltar uma delegacia do que errar a cidade.

    pdftotext -layout deam.pdf deam.txt
    python scripts/build_deam_seed.py deam.txt --saida data/seed/services_deam_cnj.csv \
        --revisao data/seed/services_deam_cnj.revisao.txt
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services import municipios as mun  # noqa: E402

FONTE_URL = (
    "https://www.cnj.jus.br/wp-content/uploads/2023/09/"
    "delegacia-especializada-de-atendimento-a-mulher-2023.pdf"
)
ATUALIZADO_EM = "2023-09-01"

ESTADOS = {
    "acre": "AC", "alagoas": "AL", "amazonas": "AM", "amapa": "AP", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "minas gerais": "MG", "mato grosso do sul": "MS",
    "mato grosso": "MT", "para": "PA", "paraiba": "PB", "pernambuco": "PE", "piaui": "PI",
    "parana": "PR", "rio de janeiro": "RJ", "rio grande do norte": "RN", "rondonia": "RO",
    "roraima": "RR", "rio grande do sul": "RS", "santa catarina": "SC", "sergipe": "SE",
    "sao paulo": "SP", "tocantins": "TO",
}  # fmt: skip

TELEFONE = re.compile(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}")
INICIO_LINHA = re.compile(r"^(?P<rotulo>[A-Za-zÀ-ÿ ]*?)\s*(?P<resto>\(\d{2}\)\s?\d.*)$")


@dataclass
class Linha:
    uf_rotulos: tuple[str | None, str | None]  # rótulo de estado anterior / seguinte
    telefone: str
    texto: str  # e-mail + endereço, já com continuações
    numero: int


def _rotulo_para_uf(rotulo: str) -> str | None:
    return ESTADOS.get(mun.normalizar(rotulo))


def ler_linhas(texto: str) -> list[Linha]:
    """Agrupa as linhas físicas do PDF em registros (um por telefone inicial)."""

    registros: list[dict] = []
    rotulos: list[tuple[int, str]] = []  # (índice do registro, UF)
    for numero, bruta in enumerate(texto.splitlines(), start=1):
        if not bruta.strip() or bruta.lstrip().startswith("Estado "):
            continue
        casou = INICIO_LINHA.match(bruta.strip())
        if casou and TELEFONE.match(casou.group("resto")):
            rotulo = casou.group("rotulo").strip()
            resto = casou.group("resto")
            registros.append({"numero": numero, "texto": resto})
            uf = _rotulo_para_uf(rotulo)
            if uf:
                rotulos.append((len(registros) - 1, uf))
            continue
        partes = re.split(r"\s{2,}", bruta.strip())
        uf = _rotulo_para_uf(partes[0])
        if uf and len(partes) == 1:
            rotulos.append((max(len(registros) - 1, 0), uf))
            continue
        if uf:  # rótulo + continuação do endereço na mesma linha
            rotulos.append((max(len(registros) - 1, 0), uf))
            partes = partes[1:]
        if registros:
            registros[-1]["texto"] += "  " + " ".join(partes)

    saida: list[Linha] = []
    for i, reg in enumerate(registros):
        anterior = next((uf for idx, uf in reversed(rotulos) if idx <= i), None)
        seguinte = next((uf for idx, uf in rotulos if idx > i), None)
        partes = re.split(r"\s{2,}", reg["texto"].strip(), maxsplit=1)
        saida.append(
            Linha(
                (anterior, seguinte), partes[0], partes[1] if len(partes) > 1 else "", reg["numero"]
            )
        )
    return saida


UFS = set(ESTADOS.values())
#: UFs cuja fonte é outra, mais precisa que o CNJ. O DF vem de scripts/build_pcdf_seed.py.
EXCLUIR_UF = {"DF"}
ALIAS = {  # grafia do PDF x IBGE
    "moji mirim": "mogi mirim",
    "nova adradina": "nova andradina",
    "embu": "embu das artes",
}
# Linhas sem município escrito no PDF, resolvidas pelo bairro/rua (conferido à mão).
MANUAL = {
    "(82) 3315-4327": ("AL", "Maceió"),  # Tabuleiro do Martins é bairro de Maceió
    "(92)3236-7012": ("AM", "Manaus"),  # Av. Mário Ypiranga fica em Manaus
}


def _chave(nome: str) -> str:
    chave = mun.normalizar(nome).replace(" ", "")
    return (
        mun.normalizar(ALIAS.get(mun.normalizar(nome), nome)).replace(" ", "")
        if (mun.normalizar(nome) in ALIAS)
        else chave
    )


def _ddd(telefone: str) -> str | None:
    achou = re.search(r"\(?(\d{2})\)?", telefone)
    return achou.group(1) if achou else None


def _nomes_candidatos(texto: str) -> list[tuple[str, str | None]]:
    """Pares (nome possível, UF indicada) em ordem de confiança."""

    texto = re.sub(r"\s+", " ", texto)
    achados: list[tuple[str, str | None]] = []
    for m in re.finditer(r"Munic[ií]pio\s*:?\s*([^.]*?)(?:\s+Cep|\.|$)", texto, re.I):
        nome = m.group(1).strip()
        barra = re.match(r"(.+?)\s*/\s*([A-Za-z]{2})$", nome)
        achados.append((barra.group(1), barra.group(2).upper()) if barra else (nome, None))
    for m in re.finditer(r"(?:/|\s[–-]\s|(?<=\w)-)([A-Za-z]{2})(?![\wÀ-ÿ])", texto):
        uf = m.group(1).upper()
        if uf not in UFS:
            continue
        palavras = texto[: m.start()].split()[-4:]
        for k in range(1, len(palavras) + 1):
            achados.append((" ".join(palavras[-k:]), uf))
    return achados


def _no_ibge(nome: str, uf: str | None) -> list[mun.Municipio]:
    alvo = _chave(nome)
    if not alvo:
        return []
    return [
        m
        for sigla, itens in mun.carregar().items()
        for m in itens
        if (uf is None or sigla == uf) and _chave(m.nome) == alvo
    ]


def resolver(linha: Linha, ddd_uf: dict[str, str] | None = None):
    """(nome, UF, município IBGE) ou None se não der para provar."""

    permitidas = {uf for uf in linha.uf_rotulos if uf}
    ddd = _ddd(linha.telefone)
    for nome, uf_dica in _nomes_candidatos(linha.texto):
        todos = _no_ibge(nome, None)
        if not todos:
            continue
        # a UF do rótulo manda; a UF escrita no texto pode estar errada ("Colatina/SE")
        certos = [m for m in todos if m.uf in permitidas]
        if len(certos) > 1 and uf_dica:
            certos = [m for m in certos if m.uf == uf_dica] or certos
        if len(certos) > 1 and ddd_uf and ddd in ddd_uf:
            certos = [m for m in certos if m.uf == ddd_uf[ddd]] or certos
        if not certos and len(todos) == 1 and not permitidas:
            certos = todos
        if len(certos) == 1:
            return certos[0].nome, certos[0].uf, certos[0]
    return None


def limpar_endereco(texto: str, municipio: str = "", uf: str = "") -> str:
    """Endereço sem e-mail, sem CEP e sem a cidade/UF repetida (a gente a reanexa depois)."""

    t = re.sub(r"\s+", " ", texto)
    t = re.sub(r"\S+@\S+", "", t)
    t = re.sub(r"\b[\w.-]+\.(?:gov|com|org|net)(?:\.br)?\b", "", t)
    t = re.sub(r"Munic[ií]pio\s*:?.*$", "", t, flags=re.I)
    t = re.sub(r"\s*Cep\.?\s*:?\s*(?:cep\s*)?[\d.]{5,6}-?\s*\d{0,3}\.?", "", t, flags=re.I)
    t = re.sub(r"\s*CEP\b.*$", "", t).strip(" .–-")
    if municipio:
        nome = r"\s+".join(re.escape(p) for p in municipio.split())
        t = re.sub(rf"\s*[–-]?\s*{nome}\s*(?:/|[–-])\s*{uf}\b\.?\s*$", "", t, flags=re.I)
        t = re.sub(rf"\s+{nome}\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" .–-")


def bairro(endereco: str) -> str | None:
    achou = re.search(r"Bairro\s*:?\s*([^–.,]+)", endereco, re.I)
    if not achou:
        return None
    nome = re.sub(r"^(?:Bairro\s*:?\s*)+", "", achou.group(1), flags=re.I).strip(" :-–")
    return nome[:60] or None


def _nome(uf: str, municipio: str, endereco: str) -> str:
    local = bairro(endereco)
    if uf == "DF":  # no DF a lista traz seções de atendimento dentro das DPs, por região
        return f"Atendimento à Mulher na delegacia - {local or municipio}"
    return f"Delegacia da Mulher (DEAM) - {local + ', ' if local else ''}{municipio}"


def construir(texto: str) -> tuple[list[dict], list[str]]:
    linhas, revisao, vistos = [], [], set()
    todas = ler_linhas(texto)
    # DDD -> UF aprendido das linhas sem ambiguidade; desempata homônimos (Santana AP/BA)
    por_ddd: dict[str, set[str]] = {}
    for linha in todas:
        achado = resolver(linha)
        if achado:
            por_ddd.setdefault(_ddd(linha.telefone) or "", set()).add(achado[1])
    ddd_uf = {d: next(iter(u)) for d, u in por_ddd.items() if d and len(u) == 1}
    consumidas: set[int] = set()
    for pos, linha in enumerate(todas):
        if pos in consumidas:
            continue
        achado = resolver(linha, ddd_uf)
        if achado is None and linha.telefone.strip() in MANUAL:
            uf_m, nome_m = MANUAL[linha.telefone.strip()]
            ibge_m = next(m for m in mun.carregar()[uf_m] if m.nome == nome_m)
            achado = (nome_m, uf_m, ibge_m)
        if achado is None and pos + 1 < len(todas):
            # a cidade veio numa linha de telefone própria ("Naviraí – MS – CEP ...")
            prox = todas[pos + 1]
            if not re.search(
                r"\b(Rua|Av|Avenida|Estrada|Rodovia|BR|Pra[cç]a|Travessa)\b", prox.texto
            ):
                juntas = Linha(
                    prox.uf_rotulos, linha.telefone, linha.texto + " " + prox.texto, linha.numero
                )
                achado = resolver(juntas, ddd_uf)
                if achado:
                    linha = Linha(
                        linha.uf_rotulos,
                        f"{linha.telefone} / {prox.telefone}",
                        juntas.texto,
                        linha.numero,
                    )
                    consumidas.add(pos + 1)
        if achado is None:
            revisao.append(
                f"linha {linha.numero}: município/UF não comprovado -> {linha.texto[:160]}"
            )
            continue
        municipio, uf, ibge = achado
        if uf in EXCLUIR_UF:
            continue
        telefone = re.sub(r"\s*/\s*", " / ", linha.telefone.strip())
        endereco = limpar_endereco(linha.texto, municipio, uf)
        if len(endereco) < 15:
            revisao.append(
                f"linha {linha.numero}: endereço incompleto no PDF ({endereco!r}), "
                f"{municipio}/{uf}, tel. {telefone}"
            )
            continue
        chave = (uf, municipio, endereco, telefone)
        if chave in vistos:
            continue
        vistos.add(chave)
        linhas.append(
            {
                "uf": uf,
                "municipio": municipio,
                "nome": _nome(uf, municipio, endereco),
                "tipo": "nucleo_atendimento_mulher" if uf == "DF" else "deam",
                "endereco": f"{endereco} - {municipio}/{uf}",
                "telefone": telefone,
                "horario": "",
                "latitude": f"{ibge.latitude:.5f}",
                "longitude": f"{ibge.longitude:.5f}",
                "coordenada_verificada": "false",
                "origem": "cnj_2023",
                "fonte_url": FONTE_URL,
                "atualizado_em": ATUALIZADO_EM,
            }
        )
    return linhas, revisao


CAMPOS = [
    "uf", "municipio", "nome", "tipo", "endereco", "telefone", "horario", "latitude",
    "longitude", "coordenada_verificada", "origem", "fonte_url", "atualizado_em",
]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("texto", type=Path, help="saída de pdftotext -layout")
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--revisao", type=Path, required=True)
    args = ap.parse_args(argv)
    linhas, revisao = construir(args.texto.read_text(encoding="utf-8"))
    with args.saida.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.DictWriter(handle, fieldnames=CAMPOS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(linhas)
    args.revisao.write_text("\n".join(revisao) + ("\n" if revisao else ""), encoding="utf-8")
    print(f"{len(linhas)} delegacias no seed, {len(revisao)} para revisão")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
