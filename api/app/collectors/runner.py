"""Dispatch collectors per source and persist snapshots.

Plain async functions (no FastAPI coupling) so Celery tasks can call them
unchanged when scheduling arrives in Phase 8.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from app.collectors.base import HTTP_TIMEOUT_SECONDS, USER_AGENT, CollectResult
from app.collectors.git import collect_git
from app.collectors.github_api import collect_github_api
from app.collectors.http import collect_http
from app.collectors.registry import REGISTRY, SourceSpec
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.source import FetchMethod
from app.services.snapshots import latest_etag, record_snapshot

# Network fetches against a handful of hosts; keep concurrency modest.
_MAX_CONCURRENT = 4


class SourceRunReport(BaseModel):
    source_id: str
    status: Literal["fetched", "not_modified", "error"]
    snapshot_created: bool = False
    content_hash: str | None = None
    error: str | None = None


async def _collect_one(
    spec: SourceSpec,
    client: httpx.AsyncClient,
    settings: Settings,
) -> CollectResult:
    if spec.method == FetchMethod.git:
        return await collect_git(spec, Path(settings.repos_dir))
    # Token-mode strategy switch (CLAUDE.md): authenticated REST + ETag when
    # a token exists and the source has a REST equivalent; otherwise token-free.
    if settings.github_token and spec.api_url:
        async with SessionLocal() as session:
            previous = await latest_etag(session, spec.api_url)
        return await collect_github_api(spec, client, settings.github_token, previous)
    return await collect_http(spec, client)


async def run_source(spec: SourceSpec, client: httpx.AsyncClient, settings: Settings) -> SourceRunReport:
    # Collectors hit the network and external processes — failures here are
    # expected operational events and must not abort the whole run.
    try:
        result = await _collect_one(spec, client, settings)
    except Exception as exc:  # noqa: BLE001 - report per-source failure, keep running
        return SourceRunReport(source_id=spec.id, status="error", error=str(exc))

    async with SessionLocal() as session:
        _, created = await record_snapshot(session, result)
    return SourceRunReport(
        source_id=spec.id,
        status=result.status,
        snapshot_created=created,
        content_hash=result.content_hash or None,
    )


async def run_sources(
    specs: tuple[SourceSpec, ...],
    settings: Settings,
) -> list[SourceRunReport]:
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        async def bounded(spec: SourceSpec) -> SourceRunReport:
            async with semaphore:
                return await run_source(spec, client, settings)

        return list(await asyncio.gather(*(bounded(s) for s in specs)))


async def run_all(settings: Settings) -> list[SourceRunReport]:
    return await run_sources(REGISTRY, settings)
