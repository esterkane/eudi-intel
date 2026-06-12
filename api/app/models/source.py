"""SourceSnapshot — the raw audit trail of every fetch (Phase 1).

Dedupe contract (BUILD_PLAN gate): a snapshot is unique by (url, content_hash).
Re-fetching unchanged content updates `last_seen_at` on the existing row instead
of inserting. Changed content inserts a new row — that history is the input to
Phase 2 diffing.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tier(str, enum.Enum):
    normative = "normative"
    reference = "reference"
    roadmap = "roadmap"
    community = "community"


class FetchMethod(str, enum.Enum):
    git = "git"
    feed = "feed"
    crawl = "crawl"
    scrape = "scrape"


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (UniqueConstraint("url", "content_hash", name="uq_snapshot_url_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    # Raw payload (atom XML, HTML, REST JSON). None for git sources, whose
    # content lives in the cloned mirror referenced by payload_ref.
    payload: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Reference to out-of-row content, e.g. the local mirror path for git repos.
    payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # ETag from authenticated GitHub REST responses (token mode only).
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
