"""Doc2query: index synthetic citizen questions next to every legal device.

The measured gap is representational: the question a victim writes and the text
a statute uses share little vocabulary, and the dense encoder only ever sees the
statute.  Doc2query closes that gap by asking the chat model what a victim would
ask about each article and appending those questions to the indexed text.

The new index is a separate collection so the production alias is untouched and
the two can be compared on identical questions.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402

D2Q_SYSTEM = (
    "Voce escreve perguntas que vitimas de violencia domestica fariam a um canal "
    "de orientacao juridica. Responda apenas com um array JSON de strings."
)
D2Q_USER = (
    "Texto legal:\n{texto}\n\n"
    "Escreva 3 perguntas curtas, em portugues coloquial, que uma vitima faria e "
    "que este texto legal responde. Nao use citacao de artigo nem numero de lei. "
    "Responda apenas com o array JSON de 3 strings."
)


def clean(text: str) -> str:
    return " ".join(text.strip().split())


def parse_list(raw: str) -> list[str]:
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        try:
            value = json.loads(raw[start : end + 1])
            if isinstance(value, list):
                return [clean(str(item)) for item in value if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return []


def artigo_of(device_id: str) -> str:
    parts = device_id.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else device_id


def load_articles(database_url: str) -> dict[str, str]:
    """One representative passage per article: the longest literal it has."""

    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select device_id, texto_literal from device_versions "
                "where texto_literal is not null and length(texto_literal) > 0"
            )
            best: dict[str, tuple[int, str]] = {}
            for device_id, texto in cur.fetchall():
                artigo = artigo_of(str(device_id))
                length = len(texto)
                if artigo not in best or length > best[artigo][0]:
                    best[artigo] = (length, texto)
    return {artigo: texto for artigo, (_, texto) in best.items()}


def generate(
    articles: dict[str, str],
    *,
    settings: Any,
    model: str,
    workers: int,
    max_tokens: int,
    out: Path,
) -> dict[str, list[str]]:
    import httpx

    existing: dict[str, list[str]] = {}
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8"))
    todo = {k: v for k, v in articles.items() if k not in existing}
    print("articles: " + str(len(articles)) + ", to generate: " + str(len(todo)), flush=True)
    if not todo:
        return existing

    url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": "Bearer " + settings.openrouter_api_key}
    only = [item.strip() for item in settings.openrouter_provider_only.split(",") if item.strip()]
    provider = {"only": only, "allow_fallbacks": False} if only else None
    print("provider pin: " + str(only or "gateway default"), flush=True)

    def one(item: tuple[str, str]) -> tuple[str, list[str]]:
        artigo, texto = item
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": D2Q_SYSTEM},
                {"role": "user", "content": D2Q_USER.format(texto=texto[:1200])},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if provider:
            body["provider"] = provider
        with httpx.Client(timeout=180.0) as client:
            response = client.post(url, json=body, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError("HTTP " + str(response.status_code) + ": " + response.text[:160])
            data = response.json()
            content = str(data["choices"][0]["message"].get("content") or "")
        return artigo, parse_list(content)[:3]

    started = time.perf_counter()
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in todo.items()]
        for index, future in enumerate(futures, 1):
            try:
                artigo, questions = future.result()
                if questions:
                    existing[artigo] = questions
            except Exception:
                errors += 1
            if index % 100 == 0:
                print(
                    "  generated "
                    + str(index)
                    + "/"
                    + str(len(futures))
                    + " ("
                    + str(round(time.perf_counter() - started))
                    + "s, "
                    + str(errors)
                    + " errors)",
                    flush=True,
                )
            if index % 400 == 0:
                out.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        "wrote " + str(out) + " (" + str(len(existing)) + " articles, " + str(errors) + " errors)"
    )
    return existing


def build_index(
    *,
    settings: Any,
    questions: dict[str, list[str]],
    database_url: str,
    collection: str,
    batch_size: int,
    source_collection: str = "devices_qdrant_dense_current",
) -> int:
    from qdrant_client import QdrantClient, models

    from src.index.qdrant import DENSE_VECTOR

    with __import__("psycopg").connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select device_id, norm_version_id, search_text from device_versions")
            rows = cur.fetchall()
    texts = {
        (str(device_id), int(version)): str(search_text or "")
        for device_id, version, search_text in rows
    }

    client = QdrantClient(url=settings.qdrant_url)
    if client.collection_exists(collection):
        client.delete_collection(collection)
    encoder = get_encoder(settings)
    size = int(getattr(encoder, "dimension", 4096))
    client.create_collection(
        collection_name=collection,
        vectors_config={
            DENSE_VECTOR: models.VectorParams(
                size=size, distance=models.Distance.COSINE, datatype=models.Datatype.FLOAT16
            )
        },
    )
    for field, schema in (
        ("norm_id", models.PayloadSchemaType.KEYWORD),
        ("vigencia_status", models.PayloadSchemaType.KEYWORD),
        ("vigencia_inicio", models.PayloadSchemaType.DATETIME),
        ("vigencia_fim", models.PayloadSchemaType.DATETIME),
    ):
        client.create_payload_index(
            collection_name=collection, field_name=field, field_schema=schema
        )

    points: list[Any] = []
    offset = None
    total = 0
    while True:
        page, offset = client.scroll(
            collection_name=source_collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in page:
            payload = dict(point.payload or {})
            device_id = str(payload.get("device_id"))
            version = int(payload.get("norm_version_id") or 0)
            base = texts.get((device_id, version), "")
            additions = questions.get(artigo_of(device_id), [])
            merged = base + (" -- " + " ; ".join(additions) if additions else "")
            points.append((str(point.id), merged, payload))
        if offset is None:
            break

    print("points to embed: " + str(len(points)), flush=True)
    started = time.perf_counter()
    chunk = max(batch_size, 256)
    for start in range(0, len(points), chunk):
        block = points[start : start + chunk]
        batches = [block[i : i + batch_size] for i in range(0, len(block), batch_size)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            encoded = list(
                pool.map(lambda b: encoder.encode_documents([item[1] for item in b]), batches)
            )
        structs = [
            models.PointStruct(
                id=item[0],
                vector={DENSE_VECTOR: [float(v) for v in vector]},
                payload=item[2],
            )
            for batch, vectors in zip(batches, encoded, strict=True)
            for item, vector in zip(batch, vectors, strict=True)
        ]
        for index in range(0, len(structs), 512):
            client.upsert(
                collection_name=collection, points=structs[index : index + 512], wait=False
            )
        total += len(structs)
        print(
            "  embedded "
            + str(total)
            + "/"
            + str(len(points))
            + " ("
            + str(round(time.perf_counter() - started))
            + "s)",
            flush=True,
        )
    deadline = time.time() + 300
    while time.time() < deadline:
        if int(client.get_collection(collection).points_count or 0) >= total:
            break
        time.sleep(3)
    print(
        "upserted "
        + str(total)
        + " points into "
        + collection
        + " (collection reports "
        + str(client.get_collection(collection).points_count)
        + ")"
    )
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--model", default="deepseek/deepseek-v4.1-flash-1017")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--questions-out", type=Path, default=ROOT / "data" / "eval" / "d2q_questions.json"
    )
    parser.add_argument("--collection", default="devices_qdrant_dense_d2q")
    parser.add_argument("--source-collection", default="devices_qdrant_dense_current")
    parser.add_argument("--phase", choices=["questions", "index", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={"database_url": args.database_url, "qdrant_url": args.qdrant_url}
    )
    articles = load_articles(args.database_url)
    if args.limit:
        articles = dict(list(articles.items())[: args.limit])

    questions: dict[str, list[str]] = {}
    if args.phase in ("questions", "all"):
        questions = generate(
            articles,
            settings=settings,
            model=args.model,
            workers=args.workers,
            max_tokens=args.max_tokens,
            out=args.questions_out,
        )
    if args.phase == "index" and args.questions_out.exists():
        questions = json.loads(args.questions_out.read_text(encoding="utf-8"))
    if args.phase in ("index", "all"):
        build_index(
            settings=settings,
            questions=questions,
            database_url=args.database_url,
            collection=args.collection,
            batch_size=args.batch_size,
            source_collection=args.source_collection,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
