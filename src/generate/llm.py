import logging
import time
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from src.generate.prompt import PROMPT_VERSION
from src.generate.schemas import LLMCitation, LLMOutput

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Raised when the LLM cannot produce a response after retries."""


class LLMClient(Protocol):
    model_name: str
    version: str

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str: ...


class MockLLM:
    """Deterministic client used by tests and demos.

    It only echoes device IDs explicitly supplied via ``context_ids`` so it can
    never invent a citation.
    """

    def __init__(
        self,
        context_ids: Sequence[str] | None = None,
        *,
        model_name: str = "mock",
        version: str = PROMPT_VERSION,
    ) -> None:
        self.context_ids = list(context_ids or [])
        self.model_name = model_name
        self.version = version

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        if not self.context_ids:
            output = LLMOutput(
                resposta=(
                    "Não encontrei base suficiente na minha base para responder com segurança."
                ),
                abstencao=True,
                motivo_abstencao="nenhum dispositivo recuperado",
                nivel_confianca="baixo",
            )
            return output.model_dump_json()

        output = LLMOutput(
            resposta="Resposta simulada com base apenas nos dispositivos recuperados.",
            citacoes=[
                LLMCitation(
                    device_id=device_id,
                    afirmacao="O dispositivo foi recuperado do contexto fornecido.",
                )
                for device_id in self.context_ids
            ],
            proximos_passos=["Procurar a Defensoria Pública."],
            encaminhamentos=[
                {
                    "tipo": "defensoria",
                    "descricao": "A Defensoria Pública pode orientar o caso.",
                }
            ],
            nivel_confianca="medio",
        )
        return output.model_dump_json()


class _HTTPLLM:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        version: str = PROMPT_VERSION,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("LLM base_url is required")
        if not api_key:
            raise ValueError("LLM api_key is required")
        if not model_name:
            raise ValueError("LLM model_name is required")

        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model_name = model_name
        self.version = version
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = client or httpx.Client()

    @property
    def endpoint(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }

    def _extract(self, response: httpx.Response) -> str:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content:
            raise ValueError("empty LLM content")
        return content

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        attempts = self.max_retries + 1
        last_error = "unknown"

        for attempt in range(attempts):
            try:
                response = self._client.post(
                    self.endpoint,
                    json=self._payload(system, user),
                    headers=self._headers(),
                    timeout=timeout,
                )
            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning("LLM request timed out attempt=%s", attempt + 1)
            except httpx.HTTPError:
                last_error = "network error"
                logger.warning("LLM request failed attempt=%s", attempt + 1)
            else:
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    last_error = f"status {response.status_code}"
                    logger.warning(
                        "LLM request failed with status=%s attempt=%s",
                        response.status_code,
                        attempt + 1,
                    )
                elif response.status_code >= 400:
                    raise LLMUnavailable(f"LLM request failed with status {response.status_code}")
                else:
                    try:
                        return self._extract(response)
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        raise LLMUnavailable("LLM returned an unexpected response") from exc

            if attempt < attempts - 1 and self.backoff_base > 0:
                time.sleep(self.backoff_base * (2**attempt))

        raise LLMUnavailable(f"LLM unavailable after {attempts} attempts: {last_error}")


class LocalLLM(_HTTPLLM):
    """Client for local OpenAI-compatible or Ollama servers."""

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/api/chat"

    def _extract(self, response: httpx.Response) -> str:
        data = response.json()
        if "choices" in data:
            return super()._extract(response)

        content = data["message"]["content"]
        if not isinstance(content, str) or not content:
            raise ValueError("empty LLM content")
        return content


class APILLM(_HTTPLLM):
    """Client for OpenAI-compatible APIs."""

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"


def get_llm(settings: object) -> LLMClient:
    provider = str(getattr(settings, "llm_provider", "mock"))
    model_name = str(getattr(settings, "llm_model", "") or "default")

    if provider == "mock":
        context_ids = getattr(settings, "mock_context_ids", None) or []
        return MockLLM(context_ids=context_ids, model_name=model_name)

    base_url = str(getattr(settings, "llm_base_url", "") or "")
    api_key = str(getattr(settings, "llm_api_key", "") or "")

    if provider == "local":
        return LocalLLM(base_url=base_url, api_key=api_key, model_name=model_name)
    if provider == "api":
        return APILLM(base_url=base_url, api_key=api_key, model_name=model_name)

    raise ValueError(f"unknown LLM provider: {provider}")
