"""Shared Ollama chat helper (local-inference skill): num_ctx capped at the 8K
budget, low temperature, thinking off, hard timeout — used by grounded
generation (Phase 5) and authoring (Phase 7)."""

from __future__ import annotations

import httpx

from app.core.config import Settings

_GEN_TIMEOUT_SECONDS = 300.0


class LlmUnavailableError(RuntimeError):
    """Raised when Ollama cannot be reached — surfaced as 503, never a hang."""


async def chat(system: str, user: str, settings: Settings, max_tokens: int = 1024) -> str:
    payload = {
        "model": settings.gen_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": settings.gen_context_tokens,
            "temperature": 0.1,
            "num_predict": max_tokens,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_GEN_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LlmUnavailableError(
            f"Ollama unavailable at {settings.ollama_base_url}: {exc}"
        ) from exc
    return str(resp.json().get("message", {}).get("content", "")).strip()
