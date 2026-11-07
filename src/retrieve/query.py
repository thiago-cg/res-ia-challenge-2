"""Query understanding with a deterministic fallback (RET-02)."""

import calendar
import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import date
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

_BR_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_YEAR_RE = re.compile(r"\bem\s+(\d{4})\b", re.IGNORECASE)
_RELATIVE_RE = re.compile(r"\bh[aá]\s+(\d+)\s+(anos?|m[eê]s(?:es)?)\b", re.IGNORECASE)
_MIN_YEAR = 1900
_MAX_RELATIVE = 120


def extract_data_fato(text: str, *, today: date | None = None) -> date | None:
    """Deterministically extract a fact date; return ``None`` when ambiguous.

    Full dates win over year/month references. Multiple distinct full dates, or
    conflicting year/relative references, are treated as ambiguous so the
    pipeline never invents a version-selection date.
    """

    if not text or not text.strip():
        return None
    reference = today or date.today()

    full_dates = _full_dates(text)
    if len(full_dates) > 1:
        return None
    if full_dates:
        return full_dates[0]

    candidates = _years(text, reference) | _relative_dates(text, reference)
    if len(candidates) == 1:
        return candidates.pop()
    return None


def _full_dates(text: str) -> list[date]:
    found: set[date] = set()
    for day_raw, month_raw, year_raw in _BR_DATE_RE.findall(text):
        candidate = _safe_date(int(year_raw), int(month_raw), int(day_raw))
        if candidate is not None:
            found.add(candidate)
    for year_raw, month_raw, day_raw in _ISO_DATE_RE.findall(text):
        candidate = _safe_date(int(year_raw), int(month_raw), int(day_raw))
        if candidate is not None:
            found.add(candidate)
    return sorted(found)


def _years(text: str, reference: date) -> set[date]:
    years = {
        date(int(year), 1, 1)
        for year in _YEAR_RE.findall(text)
        if _MIN_YEAR <= int(year) <= reference.year
    }
    return years


def _relative_dates(text: str, reference: date) -> set[date]:
    found: set[date] = set()
    for amount_raw, unit in _RELATIVE_RE.findall(text):
        amount = int(amount_raw)
        if amount <= 0 or amount > _MAX_RELATIVE:
            continue
        if unit.startswith("ano"):
            found.add(_subtract_years(reference, amount))
        else:
            found.add(_subtract_months(reference, amount))
    return found


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _subtract_years(reference: date, years: int) -> date:
    try:
        return reference.replace(year=reference.year - years)
    except ValueError:
        return reference.replace(year=reference.year - years, day=28)


def _subtract_months(reference: date, months: int) -> date:
    total = reference.year * 12 + (reference.month - 1) - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(reference.day, last_day))


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


_LEGAL_EXPANSIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bden[úu]nci(?:a|ar|ou|ando)\b", re.IGNORECASE),
        "ação penal pública incondicionada representação prazo 12 meses "
        "lesão corporal violência doméstica",
    ),
    (
        re.compile(r"boletim de ocorrência", re.IGNORECASE),
        "medida protetiva independente de boletim de ocorrência inquérito "
        "vigora enquanto persistir o risco",
    ),
    (
        re.compile(r"moro em outra cidade|não vejo|coabit|distância", re.IGNORECASE),
        "relação doméstica não exige coabitação vínculo de afetividade",
    ),
    (
        re.compile(r"advogado|dinheiro|gratuit|Defensoria", re.IGNORECASE),
        "assistência jurídica gratuita Defensoria Pública política pública de atendimento à mulher",
    ),
    (
        re.compile(r"xingando|humilhando|xingament|humilha", re.IGNORECASE),
        "violência psicológica",
    ),
    (
        re.compile(r"amea[çc]", re.IGNORECASE),
        "crime de ameaça artigo 147 prazo para representação 12 meses violência doméstica",
    ),
)


def expand_legal_query(text: str) -> str:
    """Rewrite colloquial victim language into legal search terms.

    This is the deterministic half of RET-02: it never invents facts and never
    replaces the user's question, it only appends curated legal vocabulary that
    helps dense and lexical retrieval.  An LLM rewrite can still be injected by
    the caller; this keeps the offline path useful.
    """

    expansions: list[str] = []
    for pattern, expansion in _LEGAL_EXPANSIONS:
        if pattern.search(text) and expansion not in expansions:
            expansions.append(expansion)
    if not expansions:
        return text.strip()
    return f"{text.strip()} {' '.join(expansions)}"


def _fallback_plan(text: str, facts: QueryFacts) -> QueryPlan:
    question = expand_legal_query(text)
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
