"""Importa delegacias do OpenStreetMap (Overpass) para a tabela ``services``.

    uv run python scripts/import_osm_police.py --uf DF GO --dry-run   # testa sem gravar
    uv run python scripts/import_osm_police.py                        # todos os estados
    uv run python scripts/import_osm_police.py --from-dir data/raw/osm  # offline, sem rede

Uma consulta por estado, em sequência e com pausa, para respeitar o uso justo da Overpass
(https://wiki.openstreetmap.org/wiki/Overpass_API). A resposta de cada estado fica guardada em
``data/raw/osm/<UF>.json``: reexecutar usa o arquivo e não consulta de novo (use --refresh).

Linhas curadas à mão (origem diferente de 'osm') nunca são sobrescritas, e delegacias do OSM
a menos de 350 m de uma curada são descartadas por serem a mesma. Dados © contribuidores do
OpenStreetMap, ODbL: https://www.openstreetmap.org/copyright
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.load_services import upsert  # noqa: E402
from src.services.osm import UFS, consulta_overpass, deduplicar, elemento_para_linha  # noqa: E402

# Instâncias públicas da Overpass: se uma recusar (429/504), o script tenta a próxima.
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
USER_AGENT = "zelia-project/1.0 (+https://github.com/thiago-cg/res-ia-challenge-2)"
CACHE_DIR = ROOT / "data" / "raw" / "osm"
PAUSA_ENTRE_ESTADOS_S = 10
TENTATIVAS = 4


def contexto_ssl() -> ssl.SSLContext:
    """Certificados confiáveis: o cofre do sistema (truststore, se instalado) ou o certifi.

    O Python instalado pelo uv no macOS costuma vir sem certificados, e redes de escola ou
    empresa podem reescrever o certificado: nesses casos o cofre do sistema resolve.
    """

    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class ErroDeCertificado(RuntimeError):
    """Falha de TLS: repetir não adianta, o ambiente precisa ser ajustado."""


AJUDA_CERTIFICADO = (
    "O Python não confiou no certificado do servidor. Tente: "
    "uv run --with truststore python scripts/import_osm_police.py ... "
    "(usa os certificados do sistema, inclusive os de redes que inspecionam o tráfego)."
)


class ErroOverpass(RuntimeError):
    """Nenhuma instância respondeu depois de todas as tentativas."""


def _servidor(endpoint: str) -> str:
    return urllib.parse.urlparse(endpoint).netloc


def baixar_estado(uf: str, endpoints: list[str] | str) -> dict[str, Any]:
    """Baixa um estado, passando por todas as instâncias a cada rodada e esperando entre rodadas."""

    lista = [endpoints] if isinstance(endpoints, str) else list(endpoints)
    dados = urllib.parse.urlencode({"data": consulta_overpass(uf)}).encode()
    contexto = contexto_ssl()
    motivos: list[str] = []
    for rodada in range(1, TENTATIVAS + 1):
        motivos = []
        for endpoint in lista:
            pedido = urllib.request.Request(  # noqa: S310 - endpoints https
                endpoint, data=dados, headers={"User-Agent": USER_AGENT}
            )
            try:
                with urllib.request.urlopen(pedido, timeout=300, context=contexto) as resposta:  # noqa: S310
                    return json.loads(resposta.read().decode("utf-8"))
            except urllib.error.HTTPError as erro:
                motivos.append(f"{_servidor(endpoint)}: HTTP {erro.code}")
            except urllib.error.URLError as erro:
                if isinstance(erro.reason, ssl.SSLError):
                    raise ErroDeCertificado(AJUDA_CERTIFICADO) from erro
                motivos.append(f"{_servidor(endpoint)}: {erro.reason}")
            except TimeoutError:
                motivos.append(f"{_servidor(endpoint)}: tempo esgotado")
        print()
        for motivo in motivos:
            print(f"    {motivo}")
        if rodada == TENTATIVAS:
            break
        espera = 30 * rodada
        print(f"    nova rodada em {espera}s ({rodada}/{TENTATIVAS})")
        time.sleep(espera)
    raise ErroOverpass("; ".join(motivos))


def obter_estado(
    uf: str, cache: Path, endpoints: list[str] | str, refresh: bool, offline: bool
) -> dict:
    arquivo = cache / f"{uf}.json"
    if arquivo.exists() and not refresh:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    if offline:
        raise FileNotFoundError(f"{arquivo} não existe (modo offline)")
    dados = baixar_estado(uf, endpoints)
    cache.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados


def linhas_do_estado(uf: str, dados: dict[str, Any]) -> list[dict[str, Any]]:
    linhas = [elemento_para_linha(e, uf) for e in dados.get("elements", [])]
    return [linha for linha in linhas if linha is not None]


def curadas_existentes(conn: Any) -> list[tuple[float, float, str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT latitude, longitude, tipo FROM services "
            "WHERE origem <> 'osm' AND latitude IS NOT NULL"
        )
        return [(float(a), float(b), c) for a, b, c in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--uf", nargs="+", metavar="UF", help="só estes estados (padrão: todos)")
    parser.add_argument("--from-dir", type=Path, default=CACHE_DIR, help="pasta dos JSON por UF")
    parser.add_argument("--offline", action="store_true", help="não consulta a Overpass")
    parser.add_argument("--refresh", action="store_true", help="consulta de novo mesmo com arquivo")
    parser.add_argument(
        "--endpoint", action="append", help="instância da Overpass (repita para várias)"
    )
    parser.add_argument("--database-url", default=None, help="padrão: DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="mostra o resumo sem gravar")
    args = parser.parse_args(argv)

    ufs = [u.upper() for u in args.uf] if args.uf else list(UFS)
    invalidas = [u for u in ufs if u not in UFS]
    if invalidas:
        parser.error(f"UF inválida: {', '.join(invalidas)}")

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not args.dry_run and not database_url:
        parser.error("informe --database-url ou defina DATABASE_URL (ou use --dry-run)")

    conn = None
    existentes: list[tuple[float, float, str]] = []
    if database_url:
        import psycopg

        conn = psycopg.connect(database_url)
        existentes = curadas_existentes(conn)

    total = 0
    falhas: list[str] = []
    try:
        for indice, uf in enumerate(ufs):
            print(f"{uf}: ", end="", flush=True)
            try:
                veio_do_cache = (args.from_dir / f"{uf}.json").exists() and not args.refresh
                dados = obter_estado(
                    uf, args.from_dir, args.endpoint or ENDPOINTS, args.refresh, args.offline
                )
            except ErroDeCertificado as erro:
                print(f"FALHOU\n\n{erro}")
                return 2
            except Exception as erro:  # noqa: BLE001 - segue para os outros estados
                print(f"FALHOU ({type(erro).__name__}: {erro})")
                falhas.append(uf)
                continue
            linhas = deduplicar(linhas_do_estado(uf, dados), existentes)
            mulher = sum(1 for linha in linhas if linha["tipo"] != "delegacia_comum")
            print(f"{len(linhas)} delegacia(s), {mulher} de atendimento à mulher")
            if conn is not None and not args.dry_run:
                total += upsert(conn, linhas)
            else:
                total += len(linhas)
            if not veio_do_cache and not args.offline and indice < len(ufs) - 1:
                time.sleep(PAUSA_ENTRE_ESTADOS_S)
    finally:
        if conn is not None:
            conn.close()

    verbo = "encontrada(s)" if args.dry_run else "gravada(s)"
    print(f"\n{total} delegacia(s) {verbo}.")
    if falhas:
        print(f"Falharam: {', '.join(falhas)}. Rode de novo só com --uf {' '.join(falhas)}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
