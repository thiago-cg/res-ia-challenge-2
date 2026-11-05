"""Index CLI: fallback embeddings into pgvector or target vectors into Qdrant.

``python -m src.index.run --path fallback`` reads versions from Postgres through
a :class:`VersionSource`, embeds them with the configured encoder and writes
``device_versions.embedding``.  ``--path target`` upserts the same chunks into
Qdrant.  Any failure lands in :class:`~src.contracts.IndexReport` and makes the
command exit with status 1; nothing is skipped silently.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from src.config import get_settings
from src.contracts import DeviceVersion, IndexReport
from src.index.chunk import Chunk
from src.index.embed import embed_chunks, get_encoder
from src.index.pgvector import update_embedding
from src.index.qdrant import (
    ALIAS_NAME,
    COLLECTION_PHYSICAL_NAME,
    IndexedChunk,
    ensure_collection,
    point_id,
    sparse_vector,
    upsert_chunks,
)

DEFAULT_BATCH_SIZE = 32


@runtime_checkable
class VersionSource(Protocol):
    """Reads persistable versions (with device identity) for indexing."""

    def fetch_versions(self, *, source: str | None = None) -> Iterable[Chunk]: ...


class PostgresVersionSource:
    """Join ``devices`` and ``device_versions`` into :class:`Chunk` rows."""

    SQL = """
        SELECT d.id,
               d.parent_id,
               dv.norm_version_id,
               d.norm_id,
               d.artigo_id,
               d.tipo,
               d.rotulo,
               d.caminho,
               dv.texto_literal,
               dv.contexto,
               dv.citacao,
               dv.vigencia_status,
               dv.vigencia_inicio,
               dv.vigencia_fim,
               dv.search_text,
               dv.qdrant_point_id,
               dv.content_hash
        FROM devices d
        JOIN device_versions dv ON dv.device_id = d.id
        WHERE (%s::text IS NULL OR d.norm_id = %s)
        ORDER BY d.norm_id, dv.norm_version_id, d.ordem
    """

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def fetch_versions(self, *, source: str | None = None) -> list[Chunk]:
        with self.conn.cursor() as cur:
            cur.execute(self.SQL, (source, source))
            rows = cur.fetchall()
        return [_chunk_from_row(row) for row in rows]

    def versions(self, source: str | None = None) -> list[Chunk]:
        return self.fetch_versions(source=source)


def index_fallback(
    versions: Iterable[Any],
    *,
    conn: Any | None = None,
    encoder: Any | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> IndexReport:
    """Embed chunks and write ``device_versions.embedding``."""

    encoder = encoder or get_encoder(get_settings())
    chunks, skipped, prep_errors = _prepare(versions)
    report = _report("fallback", encoder, skipped)
    report.errors.extend(prep_errors)

    if not chunks:
        return report

    if conn is None:
        conn, owned = _connect(get_settings().database_url), True
    else:
        owned = False

    try:
        embedded = embed_chunks(chunks, encoder, batch_size=batch_size)
    except Exception as exc:
        report.errors.append(f"embedding failed: {exc}")
        report.skipped += len(chunks)
        if owned:
            conn.close()
        return report

    for item in embedded:
        try:
            update_embedding(
                conn,
                item.chunk.device_id,
                item.chunk.norm_version_id,
                item.embedding,
                item.model,
                item.revision,
                item.text_hash,
            )
        except Exception as exc:
            report.errors.append(_error(item.chunk, exc))
            report.skipped += 1
        else:
            report.indexed += 1

    if owned:
        try:
            conn.commit()
        finally:
            conn.close()
    return report


def index_target(
    versions: Iterable[Any],
    *,
    client: Any | None = None,
    encoder: Any | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    collection_name: str = COLLECTION_PHYSICAL_NAME,
    alias_name: str | None = ALIAS_NAME,
) -> IndexReport:
    """Encode chunks and upsert them into the Qdrant target collection."""

    encoder = encoder or get_encoder(get_settings())
    chunks, skipped, prep_errors = _prepare(versions)
    report = _report("target", encoder, skipped)
    report.errors.extend(prep_errors)

    if client is None:
        client = make_client(get_settings().qdrant_url)

    target = alias_name or collection_name
    if hasattr(client, "collection_exists"):
        try:
            target = ensure_collection(
                client,
                collection_name=collection_name,
                alias_name=alias_name,
            )
        except Exception as exc:
            report.errors.append(f"ensure collection failed: {exc}")
            report.skipped += len(chunks)
            return report

    indexed_items: list[IndexedChunk] = []
    for chunk in chunks:
        try:
            late = _late_vectors(encoder, chunk.texto_indexacao)
            indexed_items.append(
                IndexedChunk(
                    chunk=chunk,
                    late_vectors=late,
                    bm25=sparse_vector(chunk.search_text),
                )
            )
        except Exception as exc:
            report.errors.append(_error(chunk, exc))
            report.skipped += 1

    for start in range(0, len(indexed_items), batch_size):
        batch = indexed_items[start : start + batch_size]
        try:
            upsert_chunks(client, batch, collection_name=target)
        except Exception as exc:
            report.errors.append(f"upsert failed for batch starting at {start}: {exc}")
            report.skipped += len(batch)
        else:
            report.indexed += len(batch)

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.index.run",
        description="Index legal devices into pgvector (fallback) or Qdrant (target).",
    )
    parser.add_argument("--path", choices=["fallback", "target"], required=True)
    parser.add_argument("--source", help="restrict to a norm/source id")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--qdrant-url", default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    conn = None
    try:
        settings = get_settings()
        database_url = args.database_url or settings.database_url
        conn = _connect(database_url)
        source = PostgresVersionSource(conn)
        versions = source.fetch_versions(source=args.source)

        if args.path == "fallback":
            report = index_fallback(
                versions,
                conn=conn,
                batch_size=args.batch_size,
            )
        else:
            client = make_client(args.qdrant_url or settings.qdrant_url)
            report = index_target(
                versions,
                client=client,
                batch_size=args.batch_size,
            )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    revision = report.model_revision or "-"
    print(
        f"{report.path}: indexed={report.indexed} skipped={report.skipped} "
        f"errors={len(report.errors)} model={report.model}@{revision}"
    )
    for error in report.errors:
        print(f"FAIL {error}", file=sys.stderr)
    return 1 if report.errors else 0


def make_client(url: str) -> Any:
    from qdrant_client import QdrantClient

    return QdrantClient(url=url)


def _connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(database_url)


def _prepare(versions: Iterable[Any]) -> tuple[list[Chunk], int, list[str]]:
    chunks: list[Chunk] = []
    errors: list[str] = []
    skipped = 0
    for version in versions:
        try:
            chunk = _coerce_chunk(version)
        except Exception as exc:
            skipped += 1
            errors.append(f"invalid version {type(version).__name__}: {exc}")
            continue
        if not chunk.texto_indexacao.strip():
            skipped += 1
            continue
        chunks.append(chunk)
    return chunks, skipped, errors


def _coerce_chunk(item: Any) -> Chunk:
    if isinstance(item, Chunk):
        return item
    inner = getattr(item, "chunk", None)
    if isinstance(inner, Chunk):
        return inner
    if isinstance(item, DeviceVersion):
        return _chunk_from_version(item)
    raise TypeError(f"cannot index {type(item)!r}: expected Chunk or DeviceVersion")


def _chunk_from_version(version: DeviceVersion) -> Chunk:
    return Chunk(
        device_id=version.device_id,
        parent_id=getattr(version, "parent_id", None),
        norm_version_id=version.norm_version_id,
        norm_id=getattr(version, "norm_id", ""),
        artigo_id=getattr(version, "artigo_id", version.device_id),
        tipo=getattr(version, "tipo", "artigo"),
        rotulo=getattr(version, "rotulo", ""),
        caminho=getattr(version, "caminho", ""),
        texto_literal=version.texto_literal,
        contexto=version.contexto,
        citacao=version.citacao,
        vigencia_status=version.vigencia_status,
        vigencia_inicio=version.vigencia_inicio,
        vigencia_fim=version.vigencia_fim,
        search_text=version.search_text,
        texto_indexacao=version.contexto + "\n" + version.texto_literal,
        qdrant_point_id=version.qdrant_point_id
        or point_id(version.device_id, version.norm_version_id),
        content_hash=version.content_hash,
    )


def _chunk_from_row(row: Any) -> Chunk:
    return Chunk(
        device_id=row[0],
        parent_id=row[1],
        norm_version_id=row[2],
        norm_id=row[3],
        artigo_id=row[4],
        tipo=row[5],
        rotulo=row[6],
        caminho=row[7],
        texto_literal=row[8],
        contexto=row[9],
        citacao=row[10],
        vigencia_status=row[11],
        vigencia_inicio=row[12],
        vigencia_fim=row[13],
        search_text=row[14],
        qdrant_point_id=row[15] or uuid5(NAMESPACE_URL, f"{row[0]}@{row[2]}"),
        content_hash=row[16],
        texto_indexacao=row[9] + "\n" + row[8],
    )


def _late_vectors(encoder: Any, text: str) -> list[list[float]]:
    multivector = getattr(encoder, "encode_multivectors", None)
    if callable(multivector):
        return _matrix(multivector([text])[0])

    document = getattr(encoder, "encode_document", None)
    if callable(document):
        return _matrix(document([text])[0])

    vector = encoder.encode_documents([text])[0]
    return _matrix(vector)


def _matrix(value: Any) -> list[list[float]]:
    if not value:
        return []
    first = value[0]
    if isinstance(first, (int, float)) or not hasattr(first, "__len__"):
        return [[float(item) for item in value]]
    return [[float(item) for item in row] for row in value]


def _report(path: str, encoder: Any, skipped: int) -> IndexReport:
    return IndexReport(
        path=path,  # type: ignore[arg-type]
        indexed=0,
        skipped=skipped,
        errors=[],
        model=getattr(encoder, "model_name", type(encoder).__name__),
        model_revision=getattr(encoder, "revision", None),
    )


def _error(chunk: Chunk, exc: Exception) -> str:
    return f"{chunk.device_id}@{chunk.norm_version_id}: {exc}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
