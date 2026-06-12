"""SourceSnapshot persistence with the Phase 1 dedupe contract:
unique by (url, content_hash); unchanged content refreshes last_seen_at only."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectResult
from app.models.source import SourceSnapshot


async def latest_etag(session: AsyncSession, url: str) -> str | None:
    """Most recent ETag stored for a URL (token-mode conditional requests)."""
    row = await session.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.url == url)
        .order_by(SourceSnapshot.fetched_at.desc())
        .limit(1)
    )
    return row.etag if row else None


async def record_snapshot(
    session: AsyncSession, result: CollectResult
) -> tuple[SourceSnapshot | None, bool]:
    """Persist a collect result. Returns (snapshot, created).

    - not_modified (ETag 304): refresh last_seen_at of the newest snapshot, no insert.
    - unchanged content (same url + hash): refresh last_seen_at, no insert.
    - new/changed content: insert a new snapshot row (audit trail for diffing).
    """
    now = datetime.now(tz=UTC)

    if result.status == "not_modified":
        row = await session.scalar(
            select(SourceSnapshot)
            .where(SourceSnapshot.url == result.url)
            .order_by(SourceSnapshot.fetched_at.desc())
            .limit(1)
        )
        if row is not None:
            row.last_seen_at = now
        await session.commit()
        return row, False

    existing = await session.scalar(
        select(SourceSnapshot).where(
            SourceSnapshot.url == result.url,
            SourceSnapshot.content_hash == result.content_hash,
        )
    )
    if existing is not None:
        existing.last_seen_at = now
        await session.commit()
        return existing, False

    snapshot = SourceSnapshot(
        source_id=result.source_id,
        url=result.url,
        fetched_at=now,
        last_seen_at=now,
        content_hash=result.content_hash,
        payload=result.payload,
        payload_ref=result.payload_ref,
        etag=result.etag,
    )
    session.add(snapshot)
    await session.commit()
    return snapshot, True
