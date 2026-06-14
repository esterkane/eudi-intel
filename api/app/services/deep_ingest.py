"""Deep activity ingestion — issue / PR / discussion BODIES (S1) + full threads (G1).

Phases 1–2 capture only list metadata; the body and thread of an item are the
support gold. This fetches each item's content and upserts it as a community-tier
Document keyed by the item URL, so it flows through chunk → embed → index.

Fetch strategy (token-free by default, richer with a token):
- with GITHUB_TOKEN: issues/PRs are pulled via authenticated REST — the issue/PR
  body PLUS all conversation comments (the real thread), well above the token-free
  60/hr scrape budget;
- without a token (or for discussions, which are not in the REST bucket): the HTML
  page is fetched and Trafilatura extracts the readable content.

The fetch layer always yields readable markdown; the ingest layer is source-agnostic
and idempotent (upsert_document dedupes by url + content_hash). No FastAPI coupling.
"""

from __future__ import annotations

import asyncio
import hashlib
import re

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

_KINDS: dict[str, tuple[type[GithubItemBase], str]] = {
    "issue": (Issue, "arf_issues"),
    "pull_request": (PullRequest, "arf_pulls"),
    "discussion": (Discussion, "arf_discussions"),
}
_MAX_CONCURRENT = 4
_MIN_CONTENT_CHARS = 30
_GITHUB_API = "https://api.github.com"
# issue/PR item URLs are REST-fetchable; discussions are not (GraphQL only).
_REST_ITEM = re.compile(r"github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)")
_COMMENTS_PER_PAGE = 50


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
    rest_threads: int = 0  # how many items were pulled as full REST threads
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


async def fetch_rest_thread(client: httpx.AsyncClient, html_url: str, token: str) -> str | None:
    """Issue/PR body + all conversation comments as markdown, via authenticated
    REST. None when the URL is not a REST item (e.g. a discussion)."""
    match = _REST_ITEM.search(html_url)
    if match is None:
        return None
    owner, repo, kind, number = match.groups()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"{_GITHUB_API}/repos/{owner}/{repo}"
    main_path = f"pulls/{number}" if kind == "pull" else f"issues/{number}"
    main = await client.get(f"{base}/{main_path}", headers=headers)
    main.raise_for_status()
    body = str(main.json().get("body") or "")
    comments_resp = await client.get(
        f"{base}/issues/{number}/comments?per_page={_COMMENTS_PER_PAGE}", headers=headers
    )
    comments = comments_resp.json() if comments_resp.status_code == 200 else []
    parts = [body]
    for c in comments if isinstance(comments, list) else []:
        author = c.get("user", {}).get("login", "?")
        text = str(c.get("body") or "").strip()
        if text:
            parts.append(f"Comment by {author}:\n\n{text}")
    return "\n\n---\n\n".join(p for p in parts if p.strip())


async def fetch_content(work: list[WorkItem], settings: Settings) -> dict[str, str | None]:
    """Readable markdown per item URL (REST thread when possible, else HTML)."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    results: dict[str, str | None] = {}
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:

        async def one(item: WorkItem) -> None:
            async with semaphore:
                try:
                    if settings.github_token and _REST_ITEM.search(item.url):
                        thread = await fetch_rest_thread(client, item.url, settings.github_token)
                        if thread is not None:
                            results[item.url] = thread
                            return
                    resp = await client.get(item.url)
                    resp.raise_for_status()
                    results[item.url] = html_to_markdown(resp.text)
                except Exception:  # noqa: BLE001 - failed fetch → None, reported by caller
                    results[item.url] = None

        await asyncio.gather(*(one(i) for i in work))
    return results


async def ingest_pages(
    work: list[WorkItem], contents: dict[str, str | None], settings: Settings | None = None
) -> DeepIngestReport:
    """Upsert each item's readable markdown as a community-tier Document."""
    report = DeepIngestReport()
    token_set = bool(settings.github_token) if settings else False
    async with SessionLocal() as session:
        for item in work:
            markdown = contents.get(item.url)
            if markdown is None:
                report.errors.append(f"{item.url}: fetch failed")
                continue
            report.fetched += 1
            if token_set and _REST_ITEM.search(item.url):
                report.rest_threads += 1
            if len(markdown.strip()) < _MIN_CONTENT_CHARS:
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
                title=item.title,
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
    contents = await fetch_content(work, settings)
    return await ingest_pages(work, contents, settings)
