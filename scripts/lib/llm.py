"""Wrapper Claude (anthropic SDK directo) con retry sobre errores transitorios."""
import json
import os
import re
import time
from typing import Any

import anthropic


# Modelo por defecto. Ver litellm-config.yaml para alternativos.
DEFAULT_MODEL = os.environ.get("BIZ_HUNTER_MODEL", "claude-sonnet-4-6")
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Retry sobre 429/5xx/timeouts (transitorios). NO retry sobre 400/401/403.
TRANSIENT_EXC = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _create_with_retry(*, model: str, max_tokens: int, system: str, user: str, attempts: int = 3):
    """Llama a messages.create con retry exponencial sobre errores transitorios."""
    backoff = 2.0
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return client().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except TRANSIENT_EXC as e:
            last_exc = e
            if i == attempts - 1:
                break
            sleep_s = backoff ** i
            print(f"[llm] retry {i + 1}/{attempts - 1} tras {type(e).__name__}, sleep {sleep_s}s")
            time.sleep(sleep_s)
    raise last_exc  # type: ignore[misc]


def ask_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Pide a Claude JSON estricto. Limpia code fences si los devuelve."""
    response = _create_with_retry(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=system,
        user=user,
    )
    text = response.content[0].text.strip()
    # Limpiar code fence si lo hay
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def ask_text(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
) -> str:
    """Pide a Claude texto plano."""
    response = _create_with_retry(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=system,
        user=user,
    )
    return response.content[0].text.strip()
