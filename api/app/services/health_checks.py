"""Component health probes for the Phase 0 /health gate.

Each probe returns a ComponentHealth and never raises: the whole purpose of a
health check is to *report* a downed dependency, so broad exception capture here
is intentional (not the "errors that cannot happen" the CLAUDE.md rule forbids).
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import engine


class ComponentHealth(BaseModel):
    status: str  # "ok" | "error" | "missing" | "skipped"
    detail: str


def _model_present(wanted: str, available: list[str]) -> bool:
    """Match an Ollama tag exactly, or by base name when no tag was requested."""
    if wanted in available:
        return True
    if ":" not in wanted:
        base = wanted
        return any(name.split(":")[0] == base for name in available)
    return False


async def check_postgres() -> ComponentHealth:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return ComponentHealth(status="ok", detail="SELECT 1")
    except Exception as exc:  # noqa: BLE001 - report any backend failure as unhealthy
        return ComponentHealth(status="error", detail=str(exc))


async def check_qdrant(settings: Settings) -> ComponentHealth:
    client = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        collections = await client.get_collections()
        names = sorted(c.name for c in collections.collections)
        return ComponentHealth(status="ok", detail=f"collections={names}")
    except Exception as exc:  # noqa: BLE001 - report any backend failure as unhealthy
        return ComponentHealth(status="error", detail=str(exc))
    finally:
        await client.close()


async def check_redis(settings: Settings) -> ComponentHealth:
    client: Redis = Redis.from_url(settings.redis_url)
    try:
        await client.ping()
        return ComponentHealth(status="ok", detail="PONG")
    except Exception as exc:  # noqa: BLE001 - report any backend failure as unhealthy
        return ComponentHealth(status="error", detail=str(exc))
    finally:
        await client.aclose()


async def check_ollama(settings: Settings) -> ComponentHealth:
    """Ollama reachable AND the configured generation model is pulled."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001 - report any backend failure as unhealthy
        return ComponentHealth(
            status="error",
            detail=f"Ollama unreachable at {settings.ollama_base_url}: {exc}",
        )
    if not _model_present(settings.gen_model, models):
        return ComponentHealth(
            status="missing",
            detail=f"model '{settings.gen_model}' not pulled — run: ollama pull {settings.gen_model}",
        )
    return ComponentHealth(status="ok", detail=f"model '{settings.gen_model}' present")


async def check_generation(settings: Settings) -> ComponentHealth:
    """Tiny grounded-style smoke: a one-line prompt must return text."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.gen_model,
                    "prompt": "Reply with the single word: OK",
                    "stream": False,
                    "options": {
                        "num_ctx": settings.gen_context_tokens,
                        "temperature": 0,
                    },
                },
            )
            resp.raise_for_status()
            reply = str(resp.json().get("response", "")).strip()
    except Exception as exc:  # noqa: BLE001 - report any backend failure as unhealthy
        return ComponentHealth(status="error", detail=str(exc))
    if reply:
        return ComponentHealth(status="ok", detail=f"model replied: {reply[:60]!r}")
    return ComponentHealth(status="error", detail="empty response from model")
