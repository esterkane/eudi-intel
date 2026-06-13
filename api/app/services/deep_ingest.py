"""Phase S1: deep activity ingestion — issue / PR / discussion BODIES.

Phases 1–2 capture only list metadata (title/state/url); the body and thread of
an item are the support gold and are not searchable. This fetches each item's
page (token-free HTML), extracts the readable content (Trafilatura), and upserts
it as a **community-tier** Document keyed by the item URL, so it flows through
the existing chunk → embed → index pipeline and becomes searchable.

Network and logic are split so the upsert path is testable offline:
- gather_work: which items to ingest (DB read)
- fetch_pages: token-free HTML fetch (network)
- ingest_pages: extract + upsert Documents (pure-ish; takes a {url: html} map)

Idempotent via upsert_document (dedupe by url + content_hash). No FastAPI coupling.
"""

from __future__ import annotations

import asyncio
import hashlib

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from app.collectors.base import HTTP_TIMEOUT_SECONDS, USER_AGENT
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.entities import Discussion, GithubItemBase, Issue, PullRequest
from app.models.source import Tier
from app.parsers.html import html_to_markdown
from app.parsers.markdown import chunk_markdown
from app.services.entity_upserts import upsert_document

# kind → (model, Document.source_id used for the body docs)
_KINDS: dict[str, tuple[type[GithubItemBase], str]] = {
    "issue": (Issue, "arf_issues"),
    "pull_request": (PullRequest, "arf_pulls"),
    "discussion": (Discussion, "arf_discussions"),
}
_MAX_CONCURRENT = 4
_MIN_CONTENT_CHARS = 30  # below this, the extraction is empty/boilerplate — skip


class WorkItem(BaseModel):
    source_id: str
    url: str
    title: str


class DeepIngestReport(BaseModel):
    fetched: int = 0
    documents_created: int = 0
    documents_updated: int = 0
    unchanged: int = 0
    skipped_empty: int = 0
    errors: list[str] = []


async def gather_work(kinds: tuple[str, ...], limit: int) -> list[WorkItem]:
    work: list[WorkItem] = []
    async with SessionLocal() as session:
        for kind in kinds:
            model, source_id = _KINDS[kind]
            rows = (
                await session.scalars(
                    select(model).order_by(model.updated_at.desc().nulls_last()).limit(limit)
                )
            ).all()
            work.extend(WorkItem(source_id=source_id, url=r.url, title=r.title) for r in rows)
    return work


async def fetch_pages(urls: list[str]) -> dict[str, str | None]:
    """Fetch item pages concurrently (token-free). None for a failed fetch."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    results: dict[str, str | None] = {}
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:

        async def one(url: str) -> None:
            async with semaphore:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    results[url] = resp.text
                except Exception:  # noqa: BLE001 - failed fetch → None, reported by caller
                    results[url] = None

        await asyncio.gather(*(one(u) for u in urls))
    return results


async def ingest_pages(work: list[WorkItem], pages: dict[str, str | None]) -> DeepIngestReport:
    report = DeepIngestReport()
    async with SessionLocal() as session:
        for item in work:
            html = pages.get(item.url)
            if html is None:
                report.errors.append(f"{item.url}: fetch failed")
                continue
            report.fetched += 1
            markdown = html_to_markdown(html)
            if not markdown or len(markdown.strip()) < _MIN_CONTENT_CHARS:
                report.skipped_empty += 1
                continue
            chunks = chunk_markdown(markdown, base_url=item.url)
            if not chunks:
                report.skipped_empty += 1
                continue
            outcome = await upsert_document(
                session,
                source_id=item.source_id,
                url=item.url,
                title=item.title,  # the clean list title, not the body's first heading
                tier=Tier.community,
                doc_type="html",
                content_hash=hashlib.sha256(markdown.encode()).hexdigest(),
                chunks=chunks,
            )
            if outcome == "created":
                report.documents_created += 1
            elif outcome == "updated":
                report.documents_updated += 1
            else:
                report.unchanged += 1
            await session.commit()
    return report


async def deep_ingest_activity(
    settings: Settings,
    *,
    limit: int = 40,
    kinds: tuple[str, ...] = ("issue", "pull_request", "discussion"),
) -> DeepIngestReport:
    work = await gather_work(kinds, limit)
    pages = await fetch_pages([item.url for item in work])
    return await ingest_pages(work, pages)
