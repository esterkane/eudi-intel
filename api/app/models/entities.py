"""Phase 2 first-class entities (CLAUDE.md): Document, Section, Version, Release,
Issue, Discussion, PullRequest, Milestone, RoadmapItem, VersionDiff.

Provenance invariants:
- every Document/Section carries tier + a deep-linkable URL,
- Documents dedupe by url + content_hash (idempotent re-parse),
- GitHub activity entities upsert by (repo, number).

Milestone is modelled for schema completeness; the ARF repo has zero milestones
today (verified live 2026-06-12), so nothing populates it yet — ref-impl repos
can feed it in Phase 6/8.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.source import Tier


class Maturity(str, enum.Enum):
    completed = "completed"
    in_progress = "in_progress"
    planned = "planned"
    other = "other"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    tier: Mapped[Tier] = mapped_column(String(16))
    doc_type: Mapped[str] = mapped_column(String(16))  # "markdown" | "html"
    version_or_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    sections: Mapped[list[Section]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Section.order_index"
    )


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(512))
    section_path: Mapped[str] = mapped_column(String(1024))  # "H1 > H2 > H3"
    anchor_url: Mapped[str] = mapped_column(String(1280))  # deep link (gate requirement)
    content: Mapped[str] = mapped_column(Text())
    content_hash: Mapped[str] = mapped_column(String(64))
    token_estimate: Mapped[int] = mapped_column(Integer)
    tier: Mapped[Tier] = mapped_column(String(16))  # denormalized for retrieval filters
    # content_hash at the time of the last successful vector upsert; re-embed
    # only when it differs (ingestion-pipeline idempotency rule).
    embedded_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    document: Mapped[Document] = relationship(back_populates="sections")


class Version(Base):
    """A repo tag (SemVer for the ARF). New tags trigger diffing."""

    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("source_id", "tag", name="uq_version_source_tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    tag: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (UniqueConstraint("source_id", "url", name="uq_release_source_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)


class GithubItemBase(Base):
    """Shared columns for issue-shaped GitHub activity entities."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column(String(256))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(1024))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Issue(GithubItemBase):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("repo", "number", name="uq_issue_repo_number"),)


class PullRequest(GithubItemBase):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repo", "number", name="uq_pr_repo_number"),)


class Discussion(GithubItemBase):
    __tablename__ = "discussions"
    __table_args__ = (UniqueConstraint("repo", "number", name="uq_discussion_repo_number"),)


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("repo", "title", name="uq_milestone_repo_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column(String(256))
    title: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(1024))
    due_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RoadmapItem(Base):
    """A feature-map / roadmap row with its maturity state."""

    __tablename__ = "roadmap_items"
    __table_args__ = (UniqueConstraint("source_url", "title", name="uq_roadmap_url_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    maturity: Mapped[Maturity] = mapped_column(String(16))
    anchor_url: Mapped[str | None] = mapped_column(String(1280), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VersionDiff(Base):
    """Section-level diff between two tags of a docs repo ("what changed")."""

    __tablename__ = "version_diffs"
    __table_args__ = (
        UniqueConstraint("source_id", "from_tag", "to_tag", name="uq_diff_source_tags"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    from_tag: Mapped[str] = mapped_column(String(128))
    to_tag: Mapped[str] = mapped_column(String(128))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # {files_added: [..], files_removed: [..], sections_added: [{file, path}, ..],
    #  sections_removed: [..], sections_changed: [..]}
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)
