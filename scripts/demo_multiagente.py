"""Demonstração do protótipo multiagente (Semana 4).

Roda três cenários e imprime, para cada um, a trilha de colaboração entre os agentes:

1. pergunta jurídica comum  -> Segurança → Recuperação → Resposta ⇄ Verificador
2. emergência               -> Segurança interrompe o fluxo (nenhum outro agente roda)
3. fora do corpus           -> Recuperação/Verificador forçam a abstenção com encaminhamento

Dois modos:

    # Modo offline (padrão): dados e LLM simulados, roda em qualquer computador, sem
    # Docker nem chave de API.  Serve para ensaiar e para gravar o vídeo sem risco.
    uv run python scripts/demo_multiagente.py

    # Modo real: usa Postgres, Qdrant e o LLM configurados no .env.
    uv run python scripts/demo_multiagente.py --real

Nenhuma mensagem do usuário é gravada; a trilha mostra só agente, destino e decisão.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents import MultiAgentPipeline, TracedResult  # noqa: E402

CENARIOS: list[tuple[str, str]] = [
    (
        "1. Pergunta jurídica comum",
        "O que diz o art. 7º da Lei Maria da Penha sobre as formas de violência?",
    ),
    ("2. Emergência (risco imediato)", "Ele está me batendo agora, preciso de ajuda."),
    ("3. Fora do corpus", "Qual o melhor investimento em ações para este ano?"),
]


def _banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _print(outcome: TracedResult, question: str) -> None:
    print(f"Pergunta: {question}\n")
    print("Colaboração entre os agentes:")
    for number, step in enumerate(outcome.trace.steps, start=1):
        print(
            f"  {number}. [{step.agent}] → [{step.to}]  ({step.kind}, {step.elapsed_ms:.0f} ms)\n"
            f"     {step.decision}"
        )
    answer = outcome.result.answer
    print("\nResultado:")
    print(f"  emergência: {outcome.result.emergencia}  |  abstenção: {answer.abstencao}")
    if answer.motivo_abstencao:
        print(f"  motivo da abstenção: {answer.motivo_abstencao}")
    print(f"  citações: {[c.device_id for c in answer.citacoes]}")
    print("  resposta: " + answer.resposta.strip().replace("\n", "\n            ")[:600])


# --------------------------------------------------------------------------- offline
def _offline_pipeline() -> MultiAgentPipeline:
    """Pipeline com repositório e LLM simulados (sem Docker nem API)."""

    from datetime import date

    from src.api.main import LegalRAGPipeline

    texto = (
        "Art. 7º São formas de violência doméstica e familiar contra a mulher, entre "
        "outras: I - a violência física; II - a violência psicológica; III - a violência "
        "sexual; IV - a violência patrimonial; V - a violência moral."
    )
    row = {
        "device_id": "lmp/art7",
        "norm_version_id": 1,
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
        "texto_literal": texto,
        "contexto": "Lei Maria da Penha, Título II, Capítulo I.",
        "citacao": "Lei nº 11.340/2006, art. 7º",
        "vigencia_status": "vigente",
        "vigencia_inicio": date(2006, 8, 7),
        "vigencia_fim": None,
        "fonte_url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
    }

    class DemoRepo:
        def get_device_version(self, device_id: str, norm_version_id: int) -> Any:
            return row if (device_id, norm_version_id) == ("lmp/art7", 1) else None

        def get_device_version_on(self, device_id: str, on_date: date) -> Any:
            return row if device_id == "lmp/art7" else None

        def get_current_version_id(self, device_id: str, data_fato: date | None = None) -> Any:
            return 1 if device_id == "lmp/art7" else None

        def find(self, norm_id: str, artigo_id: str) -> Any:
            if (norm_id, artigo_id) == ("lmp", "lmp/art7"):
                return {"device_id": "lmp/art7", "norm_id": "lmp", "artigo_id": "lmp/art7"}
            return None

        def lookup(self, artigo_id: str, norm_version_id: int) -> Any:
            return self.get_device_version(artigo_id, norm_version_id)

        def get_data_atualizacao_base(self) -> str:
            return "2026-11-16"

    class DemoLLM:
        model_name = "demo"
        version = "offline"

        def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
            return json.dumps(
                {
                    "resposta": (
                        "A Lei Maria da Penha reconhece cinco formas de violência doméstica "
                        "e familiar: física, psicológica, sexual, patrimonial e moral. "
                        "Esta informação não substitui atendimento jurídico individual."
                    ),
                    "citacoes": [
                        {
                            "device_id": "lmp/art7",
                            "afirmacao": "O art. 7º lista as formas de violência doméstica.",
                        }
                    ],
                    "proximos_passos": ["Procurar a Defensoria Pública ou ligar para o 180."],
                    "encaminhamentos": [],
                    "premissas": [],
                    "nivel_confianca": "alto",
                    "abstencao": False,
                    "motivo_abstencao": None,
                }
            )

    class EmptySearcher:
        def search(self, query: str, limit: int, data_fato: date | None = None) -> list[Any]:
            return []

    pipeline = LegalRAGPipeline(
        repo=DemoRepo(),
        llm=DemoLLM(),
        dense=EmptySearcher(),
        fts=EmptySearcher(),
        data_atualizacao_base="2026-11-16",
    )
    return MultiAgentPipeline(pipeline)


# --------------------------------------------------------------------------- real
def _real_pipeline() -> MultiAgentPipeline:
    from src.api.main import build_default_pipeline
    from src.config import get_settings

    settings = get_settings()
    return MultiAgentPipeline(build_default_pipeline(settings, None))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real",
        action="store_true",
        help="usa Postgres, Qdrant e LLM do .env (padrão: dados simulados offline)",
    )
    args = parser.parse_args(argv)

    multi = _real_pipeline() if args.real else _offline_pipeline()
    _banner(
        "ZELIA — protótipo multiagente ("
        + ("modo real" if args.real else "modo offline, dados simulados")
        + ")"
    )
    print("Agentes: " + ", ".join(agent.name for agent in multi.agents) + " + orquestrador")
    for titulo, pergunta in CENARIOS:
        _banner(titulo)
        _print(multi.answer_traced(pergunta), pergunta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
