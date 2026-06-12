"""Phase 0 health gate: GET /health reports Postgres, Qdrant, Redis, Ollama
(model present) and a generation smoke test. All green = gate met."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.health_checks import (
    ComponentHealth,
    check_generation,
    check_ollama,
    check_postgres,
    check_qdrant,
    check_redis,
)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    components: dict[str, ComponentHealth]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()

    postgres, qdrant, redis, ollama = await asyncio.gather(
        check_postgres(),
        check_qdrant(settings),
        check_redis(settings),
        check_ollama(settings),
    )

    if ollama.status == "ok":
        generation = await check_generation(settings)
    else:
        generation = ComponentHealth(
            status="skipped",
            detail="generation smoke skipped: model not available",
        )

    components: dict[str, ComponentHealth] = {
        "postgres": postgres,
        "qdrant": qdrant,
        "redis": redis,
        "ollama": ollama,
        "generation": generation,
    }
    overall = "ok" if all(c.status == "ok" for c in components.values()) else "degraded"
    return HealthResponse(status=overall, components=components)
