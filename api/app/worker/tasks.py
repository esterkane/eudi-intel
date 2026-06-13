"""Celery tasks (Phase 3 embedding + Phase 8 scheduled ingestion).

Each scheduled task collects one method's sources, parses what landed, and —
when content can change sections — runs the incremental embed. The feeds task
additionally triggers the targeted new-tag re-ingest (diff + history index).
Heavy work always runs here, never in API request handlers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, TypeVar

from app.collectors.registry import REGISTRY
from app.collectors.runner import run_sources
from app.core.config import Settings, get_settings
from app.db.session import engine
from app.models.source import FetchMethod
from app.services.deep_ingest import deep_ingest_activity
from app.services.parse_pipeline import parse_for_methods, reingest_new_tags
from app.services.vector_index import embed_and_index_all, embed_pending_sections
from app.worker.celery_app import celery_app

_T = TypeVar("_T")


def run_task(coro: Awaitable[_T]) -> _T:
    """Run a task coroutine on a fresh event loop, disposing the SQLAlchemy
    engine's connection pool first.

    Each Celery task uses asyncio.run() (a new loop); the module-level async
    engine pools asyncpg connections bound to whichever loop first used them.
    Without disposing, the 2nd+ task in a worker process fails with
    "Future attached to a different loop". Dispose → connections are recreated
    on the current loop. (Worker is a separate process from the API, so this
    never affects the API's long-lived pool.)
    """

    async def _wrapped() -> _T:
        await engine.dispose()
        return await coro

    return asyncio.run(_wrapped())


@celery_app.task(name="embed_and_index")
def embed_and_index() -> dict[str, Any]:
    return run_task(embed_and_index_all(get_settings()))


async def _collect_parse(
    settings: Settings, method: FetchMethod, *, embed: bool
) -> dict[str, Any]:
    specs = tuple(s for s in REGISTRY if s.method == method)
    collect_reports = await run_sources(specs, settings)
    parse_report = await parse_for_methods(settings, {method})
    embedded = await embed_pending_sections(settings) if embed else 0
    return {
        "collected": {r.source_id: r.status for r in collect_reports},
        "parsed": parse_report.model_dump(),
        "sections_embedded": embedded,
    }


@celery_app.task(name="collect_and_parse_feeds")
def collect_and_parse_feeds() -> dict[str, Any]:
    """Feeds cadence (~3h): releases/tags/commits atom. A new tag triggers the
    targeted re-ingest: version diff + history indexing (Phase 8 gate)."""

    async def run() -> dict[str, Any]:
        settings = get_settings()
        result = await _collect_parse(settings, FetchMethod.feed, embed=False)
        reingest = await reingest_new_tags(settings)
        result["reingest"] = {
            "diffs": reingest.diffs_computed,
            "errors": reingest.errors,
        }
        return result

    return run_task(run())


@celery_app.task(name="collect_and_parse_scrape")
def collect_and_parse_scrape() -> dict[str, Any]:
    """Scrape cadence (~6h): refresh issue/PR/discussion list entities, then deep-ingest
    the freshly-updated item bodies (S1) and embed them so support search stays current."""

    async def run() -> dict[str, Any]:
        settings = get_settings()
        result = await _collect_parse(settings, FetchMethod.scrape, embed=False)
        deep = await deep_ingest_activity(settings, limit=settings.deep_activity_limit)
        embedded = await embed_pending_sections(settings)
        result["deep_ingest"] = deep.model_dump()
        result["sections_embedded"] = embedded
        return result

    return run_task(run())


@celery_app.task(name="collect_and_parse_crawl")
def collect_and_parse_crawl() -> dict[str, Any]:
    """Crawl cadence (daily): docs sites + EC page → documents/sections/roadmap."""
    return run_task(_collect_parse(get_settings(), FetchMethod.crawl, embed=True))


@celery_app.task(name="collect_and_parse_git")
def collect_and_parse_git() -> dict[str, Any]:
    """Git cadence (~12h): repo pulls → documents/sections; embeds changes."""
    return run_task(_collect_parse(get_settings(), FetchMethod.git, embed=True))
