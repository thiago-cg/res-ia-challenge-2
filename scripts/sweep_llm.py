"""Query-strategy and reranking sweep with the configured chat model.

Every strategy is evaluated against the same candidate pools: the deterministic
rules expansion and each LLM variant are embedded and searched once, and the
resulting rank lists are fused with the production selection rules.  That keeps
the comparison about the strategy, not about a different retrieval budget.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._batch import OpenRouterBatch  # noqa: E402
from scripts._evalutil import aggregate, fuse_many, score_question, select  # noqa: E402
from src.api.main import PgFtsSearcher  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.eval.run import _is_answerable, load_questions  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402
from src.index.qdrant import QdrantDenseSearcher  # noqa: E402
from src.retrieve.query import expand_legal_query  # noqa: E402

PER_SEARCH_LIMIT = 50
STRIP = chr(34) + chr(39) + chr(96)

REWRITE_SYSTEM = (
    "Voce reescreve perguntas de vitimas de violencia domestica em vocabulario "
    "juridico brasileiro. Responda apenas com a pergunta reescrita, em uma linha, "
    "sem explicacao."
)
REWRITE_USER = (
    "Reescreva a pergunta abaixo usando os termos tecnicos que aparecem nos textos "
    "da Lei Maria da Penha (Lei 11.340/2006), do Codigo Penal, da Lei das "
    "Contravencoes Penais, do Codigo de Processo Penal e da Lei 14.994/2024. "
    "Nao invente fatos.\n\nPergunta: {q}"
)
APPEND_USER = (
    "Liste de 3 a 8 termos juridicos brasileiros que ajudariam a encontrar, em "
    "uma base de dispositivos legais, a resposta para a pergunta abaixo. Responda "
    "apenas com os termos separados por virgula, sem explicacao.\n\nPergunta: {q}"
)
SUBQ_SYSTEM = (
    "Voce decompoe perguntas juridicas em subperguntas de busca. Responda apenas "
    "com um array JSON de strings."
)
SUBQ_USER = (
    "Decomponha a pergunta abaixo em ate 3 subperguntas de busca curtas, cada uma "
    "usando vocabulario juridico brasileiro. Responda apenas com o array JSON.\n\n"
    "Pergunta: {q}"
)
HYDE_SYSTEM = (
    "Voce escreve trechos de legislacao brasileira. Responda apenas com o texto "
    "do dispositivo, sem comentario."
)
HYDE_USER = (
    "Escreva, em 2 ou 3 frases, o texto de um dispositivo legal brasileiro que "
    "responderia a pergunta abaixo, no estilo da lei, com verbos como devera, "
    "constitui e aplica-se.\n\nPergunta: {q}"
)
RERANK_SYSTEM = (
    "Voce ordena dispositivos legais por relevancia para uma pergunta de uma "
    "vitima de violencia domestica. Responda apenas com um array JSON de ids."
)
RERANK_USER = (
    "Pergunta: {q}\n\nCandidatos:\n{pool}\n\n"
    "Ordene TODOS os candidatos do mais para o menos relevante para responder a "
    "pergunta. Responda apenas com o array JSON dos ids, na ordem."
)


def clean(text: str) -> str:
    return " ".join(text.strip().strip(STRIP).split())


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = clean(line)
        if line:
            return line
    return ""


def parse_list(raw: str) -> list[str]:
    match = re.search(r"\[[^\]]*\]", raw, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, list):
                return [clean(str(item)) for item in value if str(item).strip()]
        except json.JSONDecodeError:
            pass
    parts = (clean(part) for part in raw.replace(chr(10), ",").split(","))
    return [item for item in parts if item][:8]


def chat(
    custom_id: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if provider:
        body["provider"] = provider
    return {"custom_id": custom_id, "method": "POST", "url": "/v1/chat/completions", "body": body}


def build_requests(
    questions: list[Any], model: str, max_tokens: int, provider: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for question in questions:
        qid = question.id
        requests.append(
            chat(
                qid + "|rewrite",
                model,
                REWRITE_SYSTEM,
                REWRITE_USER.format(q=question.pergunta),
                max_tokens,
                provider,
            )
        )
        requests.append(
            chat(
                qid + "|append",
                model,
                "",
                APPEND_USER.format(q=question.pergunta),
                max_tokens,
                provider,
            )
        )
        requests.append(
            chat(
                qid + "|subq",
                model,
                SUBQ_SYSTEM,
                SUBQ_USER.format(q=question.pergunta),
                max_tokens,
                provider,
            )
        )
        requests.append(
            chat(
                qid + "|hyde",
                model,
                HYDE_SYSTEM,
                HYDE_USER.format(q=question.pergunta),
                max_tokens,
                provider,
            )
        )
    return requests


def run_sync(settings: Any, requests: list[dict[str, Any]], *, workers: int) -> dict[str, str]:
    import httpx

    url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": "Bearer " + settings.openrouter_api_key}
    payloads = {request["custom_id"]: request["body"] for request in requests}
    out: dict[str, str] = {}
    errors: dict[str, str] = {}

    def one(custom_id: str) -> tuple[str, str]:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(url, json=payloads[custom_id], headers=headers)
            if response.status_code >= 400:
                raise RuntimeError("HTTP " + str(response.status_code) + ": " + response.text[:200])
            data = response.json()
            message = data["choices"][0]["message"]
            return custom_id, str(message.get("content") or "")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, custom_id): custom_id for custom_id in payloads}
        for index, future in enumerate(futures, 1):
            try:
                key, content = future.result()
                out[key] = content
            except Exception as exc:
                errors[futures[future]] = str(exc)[:200]
            if index % 40 == 0:
                print(
                    "  llm "
                    + str(index)
                    + "/"
                    + str(len(payloads))
                    + " ("
                    + str(round(time.perf_counter() - started))
                    + "s)",
                    flush=True,
                )
    if errors:
        print(
            "  " + str(len(errors)) + " LLM calls failed; first: " + str(list(errors.items())[0]),
            flush=True,
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data" / "eval" / "questions_150.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "eval" / "sweep_llm.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "eval" / "_llm_cache.json")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--model", default="deepseek/deepseek-v4.1-flash-1017")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--transport", choices=["sync", "batch"], default="sync")
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={"database_url": args.database_url, "qdrant_url": args.qdrant_url}
    )
    questions = [q for q in load_questions(args.questions) if _is_answerable(q)]
    if args.limit:
        questions = questions[: args.limit]
    print("answerable questions: " + str(len(questions)), flush=True)

    cache: dict[str, str] = {}
    if args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))

    only = [item.strip() for item in settings.openrouter_provider_only.split(",") if item.strip()]
    provider = {"only": only, "allow_fallbacks": False} if only else None
    print("provider pin: " + str(only or "gateway default"), flush=True)
    requests = [
        request
        for request in build_requests(questions, args.model, args.max_tokens, provider)
        if request["custom_id"] not in cache
    ]
    if requests:
        if args.transport == "batch":
            client = OpenRouterBatch(settings.openrouter_api_key, settings.openrouter_base_url)
            result = client.collect(args.model + ":batch", requests, label="query-strategies")
            cache.update({key: result.content(key) for key in result.by_id})
        else:
            cache.update(run_sync(settings, requests, workers=args.workers))
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print("cached LLM responses: " + str(len(cache)), flush=True)

    encoder = get_encoder(settings)
    dense = QdrantDenseSearcher(args.qdrant_url, encoder)
    fts = PgFtsSearcher(args.database_url)

    def pool(query: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        dense_hits = [
            (str(item.device_id), int(item.norm_version_id))
            for item in dense.search(query, PER_SEARCH_LIMIT)[:PER_SEARCH_LIMIT]
        ]
        try:
            fts_hits = [
                (str(item.device_id), int(item.norm_version_id))
                for item in fts.search(query, PER_SEARCH_LIMIT)[:PER_SEARCH_LIMIT]
            ]
        except Exception:
            fts_hits = []
        return dense_hits, fts_hits

    variants = ["rules", "raw", "rewrite", "append", "combo", "hyde", "subq"]
    rows: dict[str, list[dict[str, float]]] = {name: [] for name in variants}

    def evaluate_one(question: Any) -> tuple[str, dict[str, dict[str, float]]]:
        gold = question.device_ids
        base = question.pergunta
        rewrite = first_line(cache.get(question.id + "|rewrite", "")) or base
        appended = " ".join(parse_list(cache.get(question.id + "|append", "")))[:400]
        hyde = clean(cache.get(question.id + "|hyde", "")) or base
        subqs = [
            item for item in parse_list(cache.get(question.id + "|subq", "")) if len(item) > 12
        ][:3]

        specs: dict[str, list[str]] = {
            "rules": [expand_legal_query(base)],
            "raw": [base],
            "rewrite": [rewrite],
            "append": [base + " " + appended if appended else base],
            "combo": [expand_legal_query(rewrite)],
            "hyde": [hyde],
            "subq": subqs or [base],
        }

        scored: dict[str, dict[str, float]] = {}
        for name, queries in specs.items():
            pools = [pool(query) for query in queries]
            if len(queries) == 1:
                selected = select(pools[0][0], pools[0][1], weight=0.2, cap=3, max_devices=10)
            else:
                fused_dense = fuse_many([entry[0] for entry in pools], cap=3, max_devices=10)
                fused_fts = fuse_many([entry[1] for entry in pools], cap=3, max_devices=10)
                selected = select(
                    [(item.device_id, item.norm_version_id) for item in fused_dense],
                    [(item.device_id, item.norm_version_id) for item in fused_fts],
                    weight=0.2,
                    cap=3,
                    max_devices=10,
                )
            scored[name] = score_question([item.device_id for item in selected], gold)
        return question.id, scored

    started = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool_exec:
        for scored in pool_exec.map(evaluate_one, questions):
            for name, metrics in scored.items():
                rows[name].append(metrics)
            done += 1
            if done % 10 == 0 or done == len(questions):
                print(
                    "  evaluated "
                    + str(done)
                    + "/"
                    + str(len(questions))
                    + " ("
                    + str(round(time.perf_counter() - started))
                    + "s)",
                    flush=True,
                )

    results = [aggregate(value, name) for name, value in rows.items()]
    results.sort(key=lambda row: row["recall_at_10"], reverse=True)
    header = "strategy           R@10  ArtR@10    MRR   nDCG complete"
    print("\n" + header)
    print("-" * len(header))
    for row in results:
        print(
            "{:<16} {:>6.3f} {:>8.3f} {:>6.3f} {:>6.3f} {:>8.3f}".format(
                row["name"],
                row["recall_at_10"],
                row["article_recall_at_10"],
                row["mrr_at_10"],
                row["ndcg_at_10"],
                row["complete"],
            )
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nwrote " + str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
