"""Query understanding with a deterministic fallback (RET-02)."""

import json
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

from src.contracts import QueryFacts, QueryPlan

logger = logging.getLogger(__name__)

QUERY_UNDERSTANDING_PROMPT_V1 = """Você organiza perguntas de vítimas de violência doméstica
para busca jurídica. Versão do prompt: query_understanding_v1.

Retorne SOMENTE um objeto JSON válido com este contrato:
{
  "fatos": {
    "relacao": "companheiro|ex-companheiro|familiar|outro|desconhecido",
    "tipo_violencia": ["fisica", "psicologica", "sexual", "patrimonial", "moral", "vicaria"],
    "urgencia": "imediata|recente|passada|desconhecida",
    "data_fato": "YYYY-MM-DD|null",
    "uf": "SP|null"
  },
  "consulta_juridica": "string",
  "subperguntas": ["string"]
}

Regras:
- Não invente dados, sobretudo a data do fato: use null quando não informada.
- Gere no máximo 3 subperguntas.
- Se não houver reescrita segura, preserve a pergunta original em consulta_juridica.
- Não inclua texto fora do JSON.
"""

_MAX_CONTRACT_SUBQUESTIONS = 3


def default_facts() -> QueryFacts:
    return QueryFacts(
        relacao="desconhecido",
        tipo_violencia=[],
        urgencia="desconhecida",
        data_fato=None,
        uf=None,
    )


def build_query_understanding_prompt(text: str) -> str:
    return f"{QUERY_UNDERSTANDING_PROMPT_V1}\nPergunta da usuária:\n{text}"


def _extract_json(raw: str) -> Any:
    stripped = raw.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    raise ValueError("invalid JSON in query understanding response")


def _parse_facts(raw_facts: object, base: QueryFacts) -> QueryFacts:
    if raw_facts is None:
        return base
    if not isinstance(raw_facts, Mapping):
        raise ValueError("fatos must be an object")

    data = base.model_dump()
    for field in ("relacao", "tipo_violencia", "urgencia", "uf"):
        if field in raw_facts:
            data[field] = raw_facts[field]

    if "data_fato" in raw_facts:
        data_fato = raw_facts["data_fato"]
        data["data_fato"] = data_fato if data_fato not in ("", None) else base.data_fato

    if data.get("uf") == "":
        data["uf"] = None

    return QueryFacts.model_validate(data)


def _fallback_plan(text: str, facts: QueryFacts) -> QueryPlan:
    question = text.strip()
    return QueryPlan(
        fatos=facts,
        consulta_juridica=question,
        subperguntas=[question],
    )


def _build_plan(
    text: str,
    payload: Mapping[str, Any],
    base_facts: QueryFacts,
    *,
    preserve_facts: bool,
    max_subquestions: int,
) -> QueryPlan:
    fatos = base_facts if preserve_facts else _parse_facts(payload.get("fatos"), base_facts)

    consulta_raw = payload.get("consulta_juridica")
    consulta = (
        consulta_raw.strip()
        if isinstance(consulta_raw, str) and consulta_raw.strip()
        else text.strip()
    )

    raw_subperguntas = payload.get("subperguntas")
    if not isinstance(raw_subperguntas, list):
        raise ValueError("subperguntas must be a list")

    subperguntas = [
        item.strip() for item in raw_subperguntas if isinstance(item, str) and item.strip()
    ]
    limit = max(1, min(max_subquestions, _MAX_CONTRACT_SUBQUESTIONS))
    subperguntas = subperguntas[:limit]
    if not subperguntas:
        subperguntas = [text.strip()]

    return QueryPlan(fatos=fatos, consulta_juridica=consulta, subperguntas=subperguntas)


def understand_query(
    text: str,
    facts: QueryFacts | None = None,
    *,
    llm_call: Callable[[str], str] | None = None,
    max_subquestions: int = 3,
) -> QueryPlan:
    """Extract facts and subquestions from a question.

    Without ``llm_call`` the original question is used as the single subquestion.
    Invalid JSON, schema failures, and exceptions from the LLM fall back to that
    deterministic plan instead of raising.
    """
    base_facts = facts if facts is not None else default_facts()

    if llm_call is None:
        return _fallback_plan(text, base_facts)

    try:
        response = llm_call(build_query_understanding_prompt(text))
        payload = _extract_json(response)
        if not isinstance(payload, Mapping):
            raise ValueError("query understanding response must be an object")
        return _build_plan(
            text,
            payload,
            base_facts,
            preserve_facts=facts is not None,
            max_subquestions=max_subquestions,
        )
    except Exception as exc:
        logger.warning("query understanding fallback: %s", exc)
        return _fallback_plan(text, base_facts)
