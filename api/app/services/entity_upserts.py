"""Idempotent entity upserts (ingestion-pipeline skill: dedupe Documents by
source_url + content_hash; upsert GitHub items by repo#number)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Document,
    GithubItemBase,
    Release,
    RoadmapItem,
    Section,
    Version,
)
from app.models.source import Tier
from app.parsers.feature_map import ParsedRoadmapItem
from app.parsers.github_lists import GithubListItem
from app.parsers.markdown import SectionChunk

UpsertOutcome = Literal["created", "updated", "unchanged"]


async def upsert_document(
    session: AsyncSession,
    *,
    source_id: str,
    url: str,
    title: str,
    tier: Tier,
    doc_type: str,
    content_hash: str,
    chunks: list[SectionChunk],
    version_or_tag: str | None = None,
) -> UpsertOutcome:
    now = datetime.now(tz=UTC)
    doc = await session.scalar(select(Document).where(Document.url == url))
    if doc is not None and doc.content_hash == content_hash:
        doc.last_seen = now
        doc.title = title[:512]  # metadata refresh (e.g. title-cleaning fixes)
        return "unchanged"

    outcome: UpsertOutcome
    if doc is None:
        doc = Document(
            source_id=source_id,
            url=url,
            title=title[:512],
            tier=tier,
            doc_type=doc_type,
            version_or_tag=version_or_tag,
            content_hash=content_hash,
            first_seen=now,
            last_seen=now,
        )
        session.add(doc)
        outcome = "created"
    else:
        doc.title = title[:512]
        doc.tier = tier
        doc.content_hash = content_hash
        doc.version_or_tag = version_or_tag
        doc.last_seen = now
        doc.sections.clear()  # content changed → rebuild sections
        outcome = "updated"

    for chunk in chunks:
        doc.sections.append(
            Section(
                order_index=chunk.order_index,
                heading=chunk.heading[:512],
                section_path=chunk.section_path[:1024],
                anchor_url=chunk.anchor_url[:1280],
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_estimate=chunk.token_estimate,
                tier=tier,
            )
        )
    return outcome


async def upsert_version(
    session: AsyncSession, *, source_id: str, tag: str, url: str, published_at: datetime | None
) -> bool:
    """Returns True if the version is new."""
    existing = await session.scalar(
        select(Version).where(Version.source_id == source_id, Version.tag == tag)
    )
    if existing is not None:
        return False
    session.add(Version(source_id=source_id, tag=tag, url=url, published_at=published_at))
    return True


async def upsert_release(
    session: AsyncSession,
    *,
    source_id: str,
    title: str,
    url: str,
    published_at: datetime | None,
    summary: str | None,
) -> bool:
    existing = await session.scalar(
        select(Release).where(Release.source_id == source_id, Release.url == url)
    )
    if existing is not None:
        existing.title = title[:512]
        existing.published_at = published_at
        existing.summary = summary
        return False
    session.add(
        Release(
            source_id=source_id,
            title=title[:512],
            url=url,
            published_at=published_at,
            summary=summary,
        )
    )
    return True


async def upsert_github_items(
    session: AsyncSession,
    items: list[GithubListItem],
    model: type[GithubItemBase],
) -> int:
    """Upsert by (repo, number); returns count of new rows."""
    now = datetime.now(tz=UTC)
    created = 0
    for item in items:
        existing = await session.scalar(
            select(model).where(model.repo == item.repo, model.number == item.number)
        )
        if existing is not None:
            existing.title = item.title[:1024]
            existing.state = item.state
            existing.updated_at = item.updated_at
            existing.last_seen = now
        else:
            session.add(
                model(
                    repo=item.repo,
                    number=item.number,
                    title=item.title[:1024],
                    state=item.state,
                    url=item.url,
                    updated_at=item.updated_at,
                    last_seen=now,
                )
            )
            created += 1
    return created


async def upsert_roadmap_items(
    session: AsyncSession, items: list[ParsedRoadmapItem], source_url: str
) -> int:
    now = datetime.now(tz=UTC)
    created = 0
    for item in items:
        existing = await session.scalar(
            select(RoadmapItem).where(
                RoadmapItem.source_url == source_url, RoadmapItem.title == item.title
            )
        )
        if existing is not None:
            existing.description = item.description
            existing.maturity = item.maturity
            existing.anchor_url = item.anchor_url
            existing.last_seen = now
        else:
            session.add(
                RoadmapItem(
                    source_url=source_url,
                    title=item.title[:512],
                    description=item.description,
                    maturity=item.maturity,
                    anchor_url=item.anchor_url,
                    last_seen=now,
                )
            )
            created += 1
    return created
