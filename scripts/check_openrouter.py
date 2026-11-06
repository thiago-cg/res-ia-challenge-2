"""Live smoke test for OpenRouter chat and embeddings.

Prints model names, dimensions and latency only. It never prints the API key,
the prompts or the model output.
"""

from __future__ import annotations

import sys
import time

from src.config import get_settings
from src.generate.llm import OpenRouterLLM
from src.index.embed import OpenRouterEncoder

CHAT_PROMPT = 'Responda apenas com o JSON {"ok": true}.'


def main() -> int:
    settings = get_settings()
    api_key = settings.openrouter_api_key.strip()
    if not api_key:
        print(
            "OPENROUTER_API_KEY is not set; configure it in .env or the environment.",
            file=sys.stderr,
        )
        return 1

    failures = 0

    llm = OpenRouterLLM(
        base_url=settings.openrouter_base_url,
        api_key=api_key,
        model_name=settings.openrouter_model,
        max_retries=settings.openrouter_max_retries,
        site_url=settings.openrouter_site_url,
        app_name=settings.openrouter_app_name,
    )
    try:
        started = time.perf_counter()
        content = llm.complete("Responda apenas em JSON valido.", CHAT_PROMPT)
        latency_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:
        failures += 1
        print(f"chat=failed error={type(exc).__name__}")
    else:
        if content.strip():
            print(
                f"chat=ok model={llm.model_name} latency_ms={latency_ms:.0f} chars={len(content)}"
            )
        else:
            failures += 1
            print("chat=failed error=empty_response")
    finally:
        llm.close()

    encoder = OpenRouterEncoder(
        model=settings.openrouter_embedding_model,
        api_key=api_key,
        base_url=settings.openrouter_base_url,
        dimension=settings.openrouter_embedding_dimensions,
        batch_size=settings.openrouter_batch_size,
        timeout=settings.openrouter_timeout,
        max_retries=settings.openrouter_max_retries,
        data_collection=settings.openrouter_data_collection,
        zdr=settings.openrouter_zdr,
        site_url=settings.openrouter_site_url,
        app_name=settings.openrouter_app_name,
    )
    try:
        started = time.perf_counter()
        vector = encoder.encode_query("teste")
        latency_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:
        failures += 1
        print(f"embeddings=failed error={type(exc).__name__}")
    else:
        print(
            f"embeddings=ok model={encoder.model_name} "
            f"dimension={len(vector)} latency_ms={latency_ms:.0f}"
        )
    finally:
        encoder.close()

    if failures:
        print(f"status=failed failures={failures}")
        return 1

    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
