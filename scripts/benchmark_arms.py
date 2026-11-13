"""Quatro braços sobre as mesmas perguntas:

1. llm_pura    - o LLM responde sem nenhum contexto recuperado
2. rag_denso   - RAG com busca densa (Qdrant) + LLM
3. rag_hibrido - RAG com busca híbrida (FTS + Qdrant) + LLM
4. rag_sem_llm - mesma recuperação híbrida, resposta extrativa (sem LLM)

Todos usam o mesmo guardrail de emergência, o mesmo conjunto de perguntas e o
mesmo modelo. Saída: data/eval/benchmark_arms.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_e2e import (  # noqa: E402
    CURRENT,
    _with_progress,
    build_pipeline,
    summarize,
)
from src.api.main import LegalRAGPipeline, PostgresRepo  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.eval.pipeline import make_eval_pipeline  # noqa: E402
from src.eval.run import PipelineResult, load_questions, run_eval  # noqa: E402
from src.generate.fallback import build_safe_answer, insufficient_evidence  # noqa: E402
from src.generate.llm import get_llm  # noqa: E402
from src.generate.schemas import LLMOutputError, parse_llm_output  # noqa: E402
from src.index.embed import get_encoder  # noqa: E402
from src.safety.risk import classify_risk, emergency_answer  # noqa: E402

# --------------------------------------------------------------------------
# Braço 1: LLM pura (mesmo tom e mesmo schema JSON, mas SEM contexto)
# --------------------------------------------------------------------------
PURE_SYSTEM = """\
Você é uma assistente de informação jurídica para vítimas de violência doméstica
e familiar contra a mulher. Você não é advogada, não dá parecer e não promete
resultado. Explique o que a lei diz e indique caminhos, em português do Brasil,
em linguagem simples, com acolhimento e sem julgamento. Deixe claro que a
informação não substitui atendimento jurídico individual. Não peça nome, CPF,
endereço, telefone ou documentos.

Não há documentos de apoio: responda com o que você sabe da legislação
brasileira. Cite os dispositivos em que se baseia usando device_id neste formato:
  lmp/art5            (Lei Maria da Penha, art. 5º)
  lmp/art16-a         (art. 16-A)
  lmp/art19/par5      (art. 19, § 5º)
  lmp/art22/cpt/inc3/ali-b   (art. 22, caput, inciso III, alínea b)
  cp/art147           (Código Penal)
  cp/art103/par-unico (parágrafo único)
  cpp/art38/par2      (Código de Processo Penal)
  stj-sum-542         (Súmula 542 do STJ)
  cnj-rc-5-2020/art1  (Resolução CNJ 5/2020)
Se você não souber ou a pergunta estiver fora do tema, responda com
"abstencao": true e encaminhe para a Defensoria Pública ou para o 180.

Devolva apenas JSON, sem markdown ao redor, exatamente com estas chaves:
{"resposta": str,
 "citacoes": [{"device_id": str, "afirmacao": str}],
 "proximos_passos": [str],
 "encaminhamentos": [{"servico": str, "orientacao": str}],
 "premissas": [str],
 "nivel_confianca": "alto" | "medio" | "baixo",
 "abstencao": bool,
 "motivo_abstencao": str | null}
"""

PURE_LOG: list[dict[str, Any]] = []


def make_pure_pipeline(llm: Any, repo: Any) -> Any:
    """Pipeline de avaliação do braço LLM pura."""

    def run(question: dict[str, Any]) -> PipelineResult:
        message = str(question["pergunta"])
        started = time.perf_counter()

        def elapsed() -> float:
            return (time.perf_counter() - started) * 1000.0

        # Mesmo guardrail de emergência dos outros braços (justiça na comparação).
        if classify_risk(message).immediate:
            return PipelineResult(
                emergency=True,
                answer=emergency_answer().resposta,
                latency_ms=elapsed(),
            )

        user = message
        if question.get("data_fato"):
            user += f"\n\nData do fato: {question['data_fato']}"

        try:
            raw = llm.complete(PURE_SYSTEM, user, timeout=120)
        except Exception as exc:  # um erro de rede não derruba a rodada inteira
            PURE_LOG.append({"id": question.get("id"), "llm_error": str(exc)[:200]})
            return PipelineResult(answer="", latency_ms=elapsed())

        try:
            out = parse_llm_output(raw)  # sem allowed_ids: não há contexto
        except LLMOutputError as exc:
            PURE_LOG.append(
                {"id": question.get("id"), "parse_error": True, "detail": str(exc)[:200]}
            )
            return PipelineResult(answer=raw, latency_ms=elapsed())

        cited = [c.device_id for c in out.citacoes]
        # O id citado existe no corpus? (mede "artigo inventado")
        valid = [d for d in cited if repo.get_current_version_id(d, None) is not None]
        gold = set(question.get("device_ids", []))
        PURE_LOG.append(
            {
                "id": question.get("id"),
                "categoria": question.get("categoria"),
                "cited": cited,
                "valid": valid,
                "hit_gold": sorted(set(cited) & gold),
                "gold": sorted(gold),
                "abstained": out.abstencao,
            }
        )
        return PipelineResult(
            answer=out.resposta,
            citations=cited,
            abstained=out.abstencao,
            latency_ms=elapsed(),
        )

    return run


# --------------------------------------------------------------------------
# Braço 4: RAG sem LLM (resposta extrativa com o texto literal da lei)
# --------------------------------------------------------------------------
class ExtractivePipeline(LegalRAGPipeline):
    """Mesma recuperação; no lugar do LLM devolve os dispositivos recuperados."""

    def _generate(self, message, fatos, subperguntas, retrieved):  # type: ignore[override]
        if not retrieved or insufficient_evidence(retrieved):
            return self._abstain("sem_evidencia")
        answer = build_safe_answer(retrieved, "sem_llm")
        texto = "\n\n".join(f"{c.citacao}: {c.texto}" for c in answer.citacoes)
        answer = answer.model_copy(
            update={
                "resposta": "Trechos da lei relacionados à sua pergunta:\n\n" + texto,
                "abstencao": False,
                "motivo_abstencao": None,
            }
        )
        # Os "claims" são o texto literal da lei: groundedness = 1,0 POR CONSTRUÇÃO.
        return self._result(
            answer,
            emergencia=False,
            retrieved_ids=[d.device_id for d in retrieved],
            claims_supported=[True] * len(answer.citacoes),
        )


def pure_extra_metrics() -> dict[str, Any]:
    """Métricas extras da LLM pura (as padrão não se aplicam sem recuperação)."""

    answered = [r for r in PURE_LOG if "cited" in r]
    cited = sum(len(r["cited"]) for r in answered)
    valid = sum(len(r["valid"]) for r in answered)
    hit = sum(len(r["hit_gold"]) for r in answered)
    with_gold = [r for r in answered if r["gold"]]
    gold_total = sum(len(r["gold"]) for r in with_gold)
    gold_hit = sum(len(r["hit_gold"]) for r in with_gold)
    return {
        "respostas_com_json_valido": len(answered),
        "citacoes_total": cited,
        "taxa_citacao_inexistente": round(1 - valid / cited, 3) if cited else None,
        "precisao_vs_gold": round(hit / cited, 3) if cited else None,
        "cobertura_vs_gold": round(gold_hit / gold_total, 3) if gold_total else None,
        "erros_de_schema": sum(1 for r in PURE_LOG if r.get("parse_error")),
        "erros_de_llm": sum(1 for r in PURE_LOG if r.get("llm_error")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data" / "eval" / "questions_150.jsonl"
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "data" / "eval" / "benchmark_arms.json"
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--split",
        choices=["dev", "test"],
        default=None,
        help="usa só as perguntas do split (75 em cada; metade do tempo da rodada completa)",
    )
    parser.add_argument(
        "--arms",
        default="llm_pura,rag_denso,rag_hibrido,rag_sem_llm",
        help="lista separada por vírgula (útil para rodar um braço só)",
    )
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={
            "database_url": args.database_url,
            "qdrant_url": args.qdrant_url,
            "max_devices_per_article": 3,
        }
    )
    questions = load_questions(args.questions)
    if args.split:
        questions = [q for q in questions if q.split == args.split]
    if args.limit:
        questions = questions[: args.limit]

    encoder = get_encoder(settings)
    llm = get_llm(settings)
    repo = PostgresRepo(settings.database_url)

    def rag(mode: str, cls: type | None = None) -> Any:
        pipeline = build_pipeline(
            settings=settings,
            repo=repo,
            encoder=encoder,
            llm=llm,
            collection=CURRENT,
            mode=mode,
        )
        if cls is not None:
            pipeline.__class__ = cls  # reaproveita a mesma montagem
        return make_eval_pipeline(pipeline)

    builders = {
        "llm_pura": lambda: make_pure_pipeline(llm, repo),
        "rag_denso": lambda: rag("dense"),
        "rag_hibrido": lambda: rag("hybrid"),
        "rag_sem_llm": lambda: rag("hybrid", ExtractivePipeline),
    }
    wanted = [name.strip() for name in args.arms.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in builders]
    if unknown:
        parser.error(f"braços desconhecidos: {unknown}")

    arms: dict[str, Any] = {}

    def save() -> None:
        if "llm_pura" in arms:
            arms["llm_pura"]["extra"] = pure_extra_metrics()
        args.out.write_text(
            json.dumps(
                {"questions": len(questions), "arms": arms, "pure_log": PURE_LOG},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    for name in wanted:
        print(f"\n=== {name} ({len(questions)} perguntas) ===", flush=True)
        started = time.perf_counter()
        report = run_eval(
            questions,
            pipeline=_with_progress(builders[name](), len(questions), started),
            out_path=None,
        )
        arms[name] = summarize(name, report)
        arms[name]["by_category"] = {
            key: value.model_dump() for key, value in report.by_category.items()
        }
        save()  # grava a cada braço concluído
        print(f"  braço {name} salvo em {args.out}", flush=True)

    save()
    print("escrito", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())