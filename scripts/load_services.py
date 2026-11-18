"""Carrega delegacias/DEAMs de um CSV na tabela ``services`` (idempotente).

    uv run python scripts/apply_migrations.py        # cria as colunas de coordenadas
    uv run python scripts/load_services.py           # usa data/seed/services_df.csv
    uv run python scripts/load_services.py --dry-run # só valida, não escreve

Linhas sem latitude/longitude NÃO são carregadas: o script as lista no final para você
completar o CSV. Reexecutar não duplica linhas (upsert por uf + município + nome + endereço).
Uma linha só é atualizada por uma fonte de mesma origem: dados do OSM nunca sobrescrevem os
curados à mão.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.geo import TIPOS  # noqa: E402

DEFAULT_CSV = ROOT / "data" / "seed" / "services_df.csv"
LAT_RANGE = (-34.0, 6.0)  # Brasil continental e ilhas
LON_RANGE = (-75.0, -32.0)

UPSERT = """
INSERT INTO services
    (uf, municipio, nome, tipo, endereco, telefone, horario, latitude, longitude,
     coordenada_verificada, origem, fonte_url, atualizado_em)
VALUES
    (%(uf)s, %(municipio)s, %(nome)s, %(tipo)s, %(endereco)s, %(telefone)s, %(horario)s,
     %(latitude)s, %(longitude)s, %(coordenada_verificada)s, %(origem)s, %(fonte_url)s,
     %(atualizado_em)s)
ON CONFLICT (uf, municipio, nome, (coalesce(endereco, ''))) DO UPDATE SET
    tipo = EXCLUDED.tipo,
    telefone = EXCLUDED.telefone,
    horario = EXCLUDED.horario,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    coordenada_verificada = EXCLUDED.coordenada_verificada,
    origem = EXCLUDED.origem,
    fonte_url = EXCLUDED.fonte_url,
    atualizado_em = EXCLUDED.atualizado_em
WHERE services.origem = EXCLUDED.origem
"""


@dataclass(frozen=True)
class LoadReport:
    valid: list[dict[str, Any]]
    skipped: list[tuple[str, str]]  # (nome, motivo)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1", "sim", "yes"}


def read_services_csv(path: Path) -> LoadReport:
    valid: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for line, raw in enumerate(csv.DictReader(handle), start=2):
            nome = _clean(raw.get("nome")) or f"(linha {line})"
            tipo = _clean(raw.get("tipo"))
            if tipo not in TIPOS:
                skipped.append((nome, f"tipo inválido: {tipo!r} (use {', '.join(TIPOS)})"))
                continue
            uf, municipio = _clean(raw.get("uf")), _clean(raw.get("municipio"))
            fonte, atualizado = _clean(raw.get("fonte_url")), _clean(raw.get("atualizado_em"))
            if not (uf and len(uf) == 2 and municipio and fonte and atualizado):
                skipped.append((nome, "faltam uf/município/fonte_url/atualizado_em"))
                continue
            try:
                updated = date.fromisoformat(atualizado)
            except ValueError:
                skipped.append((nome, f"data inválida: {atualizado!r} (use AAAA-MM-DD)"))
                continue
            lat_text, lon_text = _clean(raw.get("latitude")), _clean(raw.get("longitude"))
            if lat_text is None or lon_text is None:
                skipped.append((nome, "sem latitude/longitude (preencha no CSV)"))
                continue
            try:
                lat, lon = float(lat_text), float(lon_text)
            except ValueError:
                skipped.append((nome, "latitude/longitude não numéricas"))
                continue
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
                skipped.append((nome, f"coordenada fora do Brasil: {lat}, {lon}"))
                continue
            valid.append(
                {
                    "uf": uf.upper(),
                    "municipio": municipio,
                    "nome": nome,
                    "tipo": tipo,
                    "endereco": _clean(raw.get("endereco")),
                    "telefone": _clean(raw.get("telefone")),
                    "horario": _clean(raw.get("horario")),
                    "latitude": lat,
                    "longitude": lon,
                    "coordenada_verificada": _bool(raw.get("coordenada_verificada")),
                    "origem": _clean(raw.get("origem")) or "curado",
                    "fonte_url": fonte,
                    "atualizado_em": updated,
                }
            )
    return LoadReport(valid=valid, skipped=skipped)


def upsert(conn: Any, rows: list[dict[str, Any]]) -> int:
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(UPSERT, row)
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--database-url", default=None, help="padrão: DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="valida sem escrever")
    args = parser.parse_args(argv)

    report = read_services_csv(args.csv)
    print(f"{len(report.valid)} linha(s) válida(s), {len(report.skipped)} ignorada(s)")
    for nome, motivo in report.skipped:
        print(f"  ignorada: {nome} -> {motivo}")
    unverified = [r["nome"] for r in report.valid if not r["coordenada_verificada"]]
    for nome in unverified[:10]:
        print(f"  atenção: coordenada ainda não verificada: {nome}")
    if len(unverified) > 10:
        print(f"  atenção: ... e mais {len(unverified) - 10} com coordenada aproximada")

    if args.dry_run:
        return 0
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("informe --database-url ou defina DATABASE_URL")

    import psycopg

    with psycopg.connect(database_url) as conn:
        count = upsert(conn, report.valid)
    print(f"{count} serviço(s) gravado(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
