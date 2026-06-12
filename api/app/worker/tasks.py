"""Celery tasks (Phase 3 embedding + Phase 8 scheduled ingestion).

Each scheduled task collects one method's sources, parses what landed, and —
when content can change sections — runs the incremental embed. The feeds task
additionally triggers the targeted new-tag re-ingest (diff + history index).
Heavy work always runs here, never in API request handlers.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.collectors.registry import REGISTRY
from app.collectors.runner import run_sources
from app.core.config import Settings, get_settings
from app.models.source import FetchMethod
from app.services.parse_pipeline import parse_for_methods, reingest_new_tags
from app.services.vector_index import embed_and_index_all, embed_pending_sections
from app.worker.celery_app import celery_app


@celery_app.task(name="embed_and_index")
def embed_and_index() -> dict[str, Any]:
    return asyncio.run(embed_and_index_all(get_settings()))


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

    return asyncio.run(run())


@celery_app.task(name="collect_and_parse_scrape")
def collect_and_parse_scrape() -> dict[str, Any]:
    """Scrape cadence (~6h): issue/PR/discussion list pages → activity entities."""
    return asyncio.run(_collect_parse(get_settings(), FetchMethod.scrape, embed=False))


@celery_app.task(name="collect_and_parse_crawl")
def collect_and_parse_crawl() -> dict[str, Any]:
    """Crawl cadence (daily): docs sites + EC page → documents/sections/roadmap."""
    return asyncio.run(_collect_parse(get_settings(), FetchMethod.crawl, embed=True))


@celery_app.task(name="collect_and_parse_git")
def collect_and_parse_git() -> dict[str, Any]:
    """Git cadence (~12h): repo pulls → documents/sections; embeds changes."""
    return asyncio.run(_collect_parse(get_settings(), FetchMethod.git, embed=True))
