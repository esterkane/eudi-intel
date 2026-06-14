"""Redis cache for cross-encoder rerank scores (G2 latency work).

The CPU reranker is the support console's slow step. Scores are deterministic
for a given (model, query, candidate content), so we cache them: repeated and
overlapping queries (the answer path and the related path rerank the same query;
support leads re-run symptoms) skip the cross-encoder entirely.

Best-effort: a Redis outage degrades to "all misses" and never breaks search.
"""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None
_TTL_SECONDS = 7 * 24 * 3600


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url)
    return _client


def _key(model: str, query: str, content: str) -> str:
    digest = hashlib.sha256(f"{model}\x00{query}\x00{content}".encode()).hexdigest()
    return f"rerank:{digest}"


async def get_cached_scores(model: str, query: str, contents: list[str]) -> list[float | None]:
    """Cached score per content (None on miss). All-None if Redis is unavailable."""
    if not contents:
        return []
    try:
        values = await _redis().mget([_key(model, query, c) for c in contents])
    except Exception:  # noqa: BLE001 - cache is best-effort; treat as all-miss
        return [None] * len(contents)
    return [_to_float(v) for v in values]


def _to_float(value: bytes | str | None) -> float | None:
    if value is None:
        return None
    return float(value.decode() if isinstance(value, bytes) else value)


async def store_scores(model: str, query: str, contents: list[str], scores: list[float]) -> None:
    if not contents:
        return
    try:
        pipe = _redis().pipeline()
        for content, score in zip(contents, scores):
            pipe.set(_key(model, query, content), str(score), ex=_TTL_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001 - cache is best-effort
        return
