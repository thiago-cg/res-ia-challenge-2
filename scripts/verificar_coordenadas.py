"""Confere as coordenadas das delegacias do DF cruzando fontes independentes.

Precisa de internet e deve ser rodado por uma pessoa, com revisão do resultado:

    uv run python scripts/verificar_coordenadas.py \
        data/seed/services_df.csv data/seed/services_df_pcdf.csv \
        --saida data/seed/services_df_verificado.csv --relatorio relatorio_coordenadas.csv

Para cada delegacia, reúne pontos de até quatro fontes que não dependem uma da outra:
  1. Nominatim pelo endereço (OpenStreetMap);
  2. Nominatim pelo CEP;
  3. BrasilAPI (CEP v2);
  4. delegacias já mapeadas no OpenStreetMap (Overpass), casadas pelo número ("14ª DP").
Dois pontos de fontes diferentes a até ``--raio-m`` metros um do outro contam como acordo.
Só vira "verificada" a delegacia com acordo de pelo menos duas fontes (e apenas com
``--marcar-verificada``). Sem acordo, a coordenada atual é mantida e a linha vai para a lista de
revisão manual, com o link do Google Maps de cada candidato para conferir a olho.

O relatório HTML (``--mapa``) mostra tudo num mapa: abra e confira os pinos antes de commitar.
Dados © contribuidores do OpenStreetMap (ODbL).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.geo import haversine_km  # noqa: E402

USER_AGENT = "zelia-delegacias/1.0 (projeto academico; verificacao de coordenadas)"
# Caixa do Distrito Federal, com folga: o que cair fora é descartado.
DF_LAT = (-16.10, -15.45)
DF_LON = (-48.30, -47.30)

Fonte = Callable[[dict[str, str]], list[tuple[float, float]]]


@dataclass
class Candidato:
    fonte: str
    latitude: float
    longitude: float


@dataclass
class Resultado:
    linha: dict[str, str]
    candidatos: list[Candidato] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    fontes_em_acordo: list[str] = field(default_factory=list)

    @property
    def confianca(self) -> str:
        if len(self.fontes_em_acordo) >= 2:
            return "alta"
        if len(self.fontes_em_acordo) == 1:
            return "media"
        return "sem_acordo"


def no_df(lat: float, lon: float) -> bool:
    return DF_LAT[0] <= lat <= DF_LAT[1] and DF_LON[0] <= lon <= DF_LON[1]


def extrair_cep(endereco: str) -> str | None:
    achado = re.search(r"CEP\s*(\d{5})-?(\d{3})", endereco or "")
    return f"{achado.group(1)}{achado.group(2)}" if achado else None


def endereco_sem_cep(endereco: str) -> str:
    return re.sub(r"\s*[–-]\s*CEP.*$", "", endereco or "").strip()


def numero_da_delegacia(nome: str) -> str | None:
    achado = re.match(r"\s*0*(\d+)\s*[ªa°º]", nome or "")
    return achado.group(1) if achado else None


def _par(lat: Any, lon: Any) -> tuple[float, float] | None:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return (la, lo) if no_df(la, lo) else None


def ponto_da_brasilapi(dados: dict[str, Any]) -> tuple[float, float] | None:
    """BrasilAPI v2: {"location": {"coordinates": {"latitude": "...", "longitude": "..."}}}."""

    coords = ((dados or {}).get("location") or {}).get("coordinates") or {}
    return _par(coords.get("latitude"), coords.get("longitude"))


def pontos_osm_com_numero(
    elementos: Sequence[dict[str, Any]],
) -> dict[str, list[tuple[float, float]]]:
    """Agrupa os pontos do Overpass pelo número da delegacia que aparece no nome."""

    por_numero: dict[str, list[tuple[float, float]]] = {}
    for elemento in elementos:
        tags = elemento.get("tags") or {}
        nome = " ".join(str(tags.get(k, "")) for k in ("name", "official_name", "alt_name", "ref"))
        numero = re.search(r"\b0*(\d{1,2})\s*[ªa°º]", nome)
        centro = elemento.get("center") or elemento
        ponto = _par(centro.get("lat"), centro.get("lon"))
        if numero and ponto:
            por_numero.setdefault(numero.group(1), []).append(ponto)
    return por_numero


def consenso(
    atual: tuple[float, float],
    candidatos: Sequence[Candidato],
    *,
    raio_m: float = 300.0,
    max_km: float = 10.0,
) -> tuple[tuple[float, float] | None, list[str]]:
    """Maior grupo de fontes diferentes a até ``raio_m`` uma da outra.

    Descarta ponto fora do DF ou a mais de ``max_km`` da coordenada atual (achado em outro lugar).
    Devolve o ponto médio do grupo e as fontes que concordam; com empate, o mais perto do atual.
    """

    validos = [
        c
        for c in candidatos
        if no_df(c.latitude, c.longitude)
        and haversine_km(atual[0], atual[1], c.latitude, c.longitude) <= max_km
    ]
    melhor: list[Candidato] = []
    for base in validos:
        grupo = [
            c
            for c in validos
            if haversine_km(base.latitude, base.longitude, c.latitude, c.longitude) * 1000 <= raio_m
        ]
        fontes = {c.fonte for c in grupo}
        # um ponto por fonte: o mais próximo do ponto base
        unico = {
            f: min(
                (c for c in grupo if c.fonte == f),
                key=lambda c: haversine_km(base.latitude, base.longitude, c.latitude, c.longitude),
            )
            for f in fontes
        }
        escolhido = list(unico.values())
        if len(escolhido) > len(melhor):
            melhor = escolhido
    if not melhor:
        return None, []
    lat = sum(c.latitude for c in melhor) / len(melhor)
    lon = sum(c.longitude for c in melhor) / len(melhor)
    return (round(lat, 6), round(lon, 6)), sorted(c.fonte for c in melhor)


def verificar(
    linhas: Sequence[dict[str, str]],
    fontes: dict[str, Fonte],
    *,
    raio_m: float = 300.0,
    max_km: float = 10.0,
) -> list[Resultado]:
    resultados = []
    for linha in linhas:
        resultado = Resultado(linha=linha)
        for nome_fonte, buscar in fontes.items():
            try:
                pontos = buscar(linha)
            except Exception as exc:  # uma fonte fora do ar não derruba as outras
                print(
                    f"  aviso: {nome_fonte} falhou em {linha['nome'][:40]!r}: {type(exc).__name__}"
                )
                pontos = []
            resultado.candidatos += [Candidato(nome_fonte, la, lo) for la, lo in pontos]
        atual = (float(linha["latitude"]), float(linha["longitude"]))
        ponto, concordam = consenso(atual, resultado.candidatos, raio_m=raio_m, max_km=max_km)
        if ponto:
            resultado.latitude, resultado.longitude = ponto
            resultado.fontes_em_acordo = concordam
        resultados.append(resultado)
    return resultados


# --- fontes reais (rede) ------------------------------------------------------------------


def criar_fontes_de_rede(pausa: float = 1.1) -> dict[str, Fonte]:
    import httpx

    http = httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
    osm_cache: dict[str, list[tuple[float, float]]] | None = None

    def nominatim(consulta: str) -> list[tuple[float, float]]:
        params = {
            "q": f"{consulta}, Distrito Federal, Brasil",
            "countrycodes": "br",
            "format": "jsonv2",
            "limit": "3",
            "viewbox": f"{DF_LON[0]},{DF_LAT[1]},{DF_LON[1]},{DF_LAT[0]}",
            "bounded": "1",
        }
        resposta = http.get("https://nominatim.openstreetmap.org/search", params=params)
        time.sleep(pausa)  # política do Nominatim: no máximo 1 requisição por segundo
        resposta.raise_for_status()
        achados = [_par(a.get("lat"), a.get("lon")) for a in resposta.json()]
        return [p for p in achados if p]

    def por_endereco(linha: dict[str, str]) -> list[tuple[float, float]]:
        texto = endereco_sem_cep(linha.get("endereco", ""))
        return nominatim(texto) if texto else []

    def por_cep_nominatim(linha: dict[str, str]) -> list[tuple[float, float]]:
        cep = extrair_cep(linha.get("endereco", ""))
        return nominatim(cep) if cep else []

    def brasilapi(linha: dict[str, str]) -> list[tuple[float, float]]:
        cep = extrair_cep(linha.get("endereco", ""))
        if not cep:
            return []
        resposta = http.get(f"https://brasilapi.com.br/api/cep/v2/{cep}")
        if resposta.status_code == 404:
            return []
        resposta.raise_for_status()
        ponto = ponto_da_brasilapi(resposta.json())
        return [ponto] if ponto else []

    def osm(linha: dict[str, str]) -> list[tuple[float, float]]:
        nonlocal osm_cache
        if osm_cache is None:
            consulta = (
                "[out:json][timeout:90];area['ISO3166-2'='BR-DF']->.df;"
                "(nwr['amenity'='police'](area.df););out center tags;"
            )
            resposta = http.post(
                "https://overpass-api.de/api/interpreter", data={"data": consulta}, timeout=120
            )
            resposta.raise_for_status()
            osm_cache = pontos_osm_com_numero(resposta.json().get("elements", []))
        numero = numero_da_delegacia(linha.get("nome", ""))
        return osm_cache.get(numero or "", [])

    return {
        "nominatim_endereco": por_endereco,
        "nominatim_cep": por_cep_nominatim,
        "brasilapi_cep": brasilapi,
        "osm_mapeada": osm,
    }


# --- saída --------------------------------------------------------------------------------


MODELO_MAPA = """<!doctype html><meta charset="utf-8"><title>Conferência de coordenadas</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
body { margin: 0; font: 14px system-ui }
#m { height: 100vh }
#l { position: absolute; z-index: 999; top: 8px; right: 8px; background: #fff;
     padding: 8px 12px; border-radius: 8px; max-width: 260px }
</style>
<div id="m"></div>
<div id="l"><b>Verde</b>: novo ponto (2+ fontes de acordo) · <b>Azul</b>: ponto atual ·
<b>Cinza</b>: candidatos de cada fonte.<br>Clique num pino para ver o nome e confira se ele
está sobre a delegacia.</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const itens = __DADOS__;
const m = L.map('m').setView([-15.8, -47.9], 11);
const tiles = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
L.tileLayer(tiles, {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(m);
const ponto = (xy, cor, texto) => {
  const pino = L.circleMarker(xy, {radius: 7, color: cor, fillColor: cor, fillOpacity: .8});
  const caixa = document.createElement('div');
  caixa.textContent = texto;
  return pino.bindPopup(caixa).addTo(m);
};
for (const i of itens) {
  ponto(i.atual, '#2457d6', i.nome + ' — ponto atual');
  if (i.novo) ponto(i.novo, '#1f6b57', i.nome + ' — novo ponto (' + i.confianca + ')');
  for (const [f, la, lo] of i.candidatos) ponto([la, lo], '#888', i.nome + ' — ' + f);
}
</script>"""


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def escrever_csv(
    resultados: Sequence[Resultado], campos: list[str], saida: Path, *, marcar_verificada: bool
) -> tuple[int, int]:
    atualizadas = verificadas = 0
    with saida.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.DictWriter(handle, fieldnames=campos, lineterminator="\n")
        escritor.writeheader()
        for r in resultados:
            nova = dict(r.linha)
            if r.confianca == "alta" and r.latitude is not None and r.longitude is not None:
                nova["latitude"], nova["longitude"] = f"{r.latitude:.5f}", f"{r.longitude:.5f}"
                atualizadas += 1
                if marcar_verificada:
                    nova["coordenada_verificada"] = "true"
                    verificadas += 1
            escritor.writerow(nova)
    return atualizadas, verificadas


def escrever_relatorio(resultados: Sequence[Resultado], destino: Path) -> None:
    with destino.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.writer(handle, lineterminator="\n")
        escritor.writerow(
            [
                "confianca",
                "nome",
                "endereco",
                "fontes_em_acordo",
                "novo_ponto",
                "ponto_atual",
                "candidatos",
            ]
        )
        for r in resultados:
            atual = (float(r.linha["latitude"]), float(r.linha["longitude"]))
            novo = (
                maps_link(r.latitude, r.longitude)
                if r.latitude is not None and r.longitude is not None
                else ""
            )
            candidatos = " | ".join(
                f"{c.fonte}: {maps_link(c.latitude, c.longitude)}" for c in r.candidatos
            )
            escritor.writerow(
                [
                    r.confianca,
                    r.linha["nome"],
                    r.linha.get("endereco", ""),
                    "+".join(r.fontes_em_acordo),
                    novo,
                    maps_link(*atual),
                    candidatos,
                ]
            )


def escrever_mapa(resultados: Sequence[Resultado], destino: Path) -> None:
    itens = []
    for r in resultados:
        itens.append(
            {
                "nome": r.linha["nome"],
                "confianca": r.confianca,
                "atual": [float(r.linha["latitude"]), float(r.linha["longitude"])],
                "novo": [r.latitude, r.longitude] if r.latitude is not None else None,
                "candidatos": [[c.fonte, c.latitude, c.longitude] for c in r.candidatos],
            }
        )
    dados = json.dumps(itens, ensure_ascii=False).replace("</", "<\\/")
    destino.write_text(MODELO_MAPA.replace("__DADOS__", dados), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entradas", type=Path, nargs="+", help="CSVs de serviços do DF")
    ap.add_argument("--saida", type=Path, help="CSV único com todas as linhas (coordenadas novas)")
    ap.add_argument("--relatorio", type=Path, default=Path("relatorio_coordenadas.csv"))
    ap.add_argument("--mapa", type=Path, default=Path("conferencia_coordenadas.html"))
    ap.add_argument(
        "--raio-m", type=float, default=300.0, help="distância para duas fontes 'concordarem'"
    )
    ap.add_argument(
        "--max-km", type=float, default=10.0, help="descarta achado longe do ponto atual"
    )
    ap.add_argument(
        "--marcar-verificada",
        action="store_true",
        help="coordenada_verificada=true quando 2+ fontes concordam",
    )
    args = ap.parse_args(argv)

    linhas: list[dict[str, str]] = []
    campos: list[str] = []
    for caminho in args.entradas:
        with caminho.open(encoding="utf-8", newline="") as handle:
            leitor = csv.DictReader(handle)
            campos = campos or list(leitor.fieldnames or [])
            linhas += [
                r for r in leitor if r["uf"] == "DF" and r.get("latitude") and r.get("longitude")
            ]
    print(f"{len(linhas)} delegacias do DF. Consultando as fontes (leva alguns minutos)…")

    resultados = verificar(linhas, criar_fontes_de_rede(), raio_m=args.raio_m, max_km=args.max_km)
    escrever_relatorio(resultados, args.relatorio)
    escrever_mapa(resultados, args.mapa)
    if args.saida:
        atualizadas, verificadas = escrever_csv(
            resultados, campos, args.saida, marcar_verificada=args.marcar_verificada
        )
        print(f"{atualizadas} coordenadas atualizadas ({verificadas} marcadas como verificadas).")
    por_nivel = {
        n: sum(1 for r in resultados if r.confianca == n) for n in ("alta", "media", "sem_acordo")
    }
    print(f"Confiança: {por_nivel}. Relatório: {args.relatorio}. Mapa: {args.mapa}")
    for r in resultados:
        if r.confianca != "alta":
            print(f"  REVISAR ({r.confianca}): {r.linha['nome'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
