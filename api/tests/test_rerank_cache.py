"""Rerank score cache (live Redis; degrades gracefully when absent)."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

import app.services.rerank_cache as cache
from app.services.rerank_cache import get_cached_scores, store_scores

REDIS_URL = "redis://localhost:6379/0"


@pytest.fixture
async def redis_up(monkeypatch: pytest.MonkeyPatch) -> bool:
    client: Redis = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:  # noqa: BLE001
        await client.aclose()
        pytest.skip("Redis not reachable")
    # the module would otherwise use the in-container hostname (redis://redis)
    monkeypatch.setattr(cache, "_client", client)
    return True


async def test_store_then_hit(redis_up: bool) -> None:
    model = "test-model"
    query = f"q-{uuid.uuid4().hex[:8]}"
    contents = ["alpha content", "beta content"]

    miss = await get_cached_scores(model, query, contents)
    assert miss == [None, None]  # cold

    await store_scores(model, query, contents, [0.9, 0.1])
    hit = await get_cached_scores(model, query, contents)
    assert hit == [pytest.approx(0.9), pytest.approx(0.1)]


async def test_partial_hit(redis_up: bool) -> None:
    model = "test-model"
    query = f"q-{uuid.uuid4().hex[:8]}"
    await store_scores(model, query, ["seen"], [0.5])
    scores = await get_cached_scores(model, query, ["seen", "unseen"])
    assert scores[0] == pytest.approx(0.5)
    assert scores[1] is None  # only the seen content is cached


async def test_empty_contents() -> None:
    assert await get_cached_scores("m", "q", []) == []
