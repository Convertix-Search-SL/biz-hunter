"""Wrapper Claude (anthropic SDK directo)."""
import json
import os
import re
from typing import Any

import anthropic


# Modelo por defecto. Ver litellm-config.yaml para alternativos.
DEFAULT_MODEL = os.environ.get("BIZ_HUNTER_MODEL", "claude-sonnet-4-6")
HAIKU_MODEL = "claude-haiku-4-5-20251001"


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def ask_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Pide a Claude JSON estricto. Limpia code fences si los devuelve."""
    response = client().messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
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
    response = client().messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()
