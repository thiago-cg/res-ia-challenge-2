import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class LLMOutputError(Exception):
    """Raised when the LLM output is not valid JSON or does not match the schema."""


class LLMCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    afirmacao: str


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resposta: str
    citacoes: list[LLMCitation] = Field(default_factory=list)
    proximos_passos: list[str] = Field(default_factory=list)
    encaminhamentos: list[dict] = Field(default_factory=list)
    premissas: list[str] = Field(default_factory=list)
    nivel_confianca: Literal["alto", "medio", "baixo"] = "baixo"
    abstencao: bool = False
    motivo_abstencao: str | None = None


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_markdown_fence(raw: str) -> str:
    stripped = raw.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _format_validation_error(error: ValidationError) -> str:
    parts = []
    for detail in error.errors():
        location = ".".join(str(item) for item in detail["loc"]) or "<root>"
        parts.append(f"{location}: {detail['msg']}")
    return "; ".join(parts)


def parse_llm_output(raw: str) -> LLMOutput:
    content = _strip_markdown_fence(raw)

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"JSON inválido na saída do LLM: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise LLMOutputError("JSON inválido na saída do LLM: esperado um objeto.")

    try:
        return LLMOutput.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(
            f"Schema inválido na saída do LLM: {_format_validation_error(exc)}"
        ) from exc
