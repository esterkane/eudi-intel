"""Dashboard endpoints (dashboard-views skill): four live views backed by
normalized entities. Every item carries a primary source URL, a timestamp, and
tier/maturity where relevant — no card without a source link."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import (
    Discussion,
    Issue,
    PullRequest,
    Release,
    RoadmapItem,
    VersionDiff,
)
from app.services.summarize import summaries_for_urls

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

EntityDigest = dict[str, object]


# ── 1. Latest Releases & What Changed ────────────────────────────────────────


class ReleaseCard(BaseModel):
    title: str
    url: str
    source_id: str
    published_at: datetime | None
    summary: EntityDigest | None = None  # cached S2 structured summary


class DiffCard(BaseModel):
    source_id: str
    from_tag: str
    to_tag: str
    computed_at: datetime
    summary: dict[str, int]
    sections_changed: list[dict[str, str]]


class ReleasesView(BaseModel):
    releases: list[ReleaseCard]
    diffs: list[DiffCard]


@router.get("/releases", response_model=ReleasesView)
async def releases_view(limit: int = Query(default=20, ge=1, le=100)) -> ReleasesView:
    async with SessionLocal() as session:
        releases = (
            await session.scalars(
                select(Release).order_by(Release.published_at.desc().nulls_last()).limit(limit)
            )
        ).all()
        diffs = (
            await session.scalars(
                select(VersionDiff).order_by(VersionDiff.computed_at.desc()).limit(5)
            )
        ).all()
        summaries = await summaries_for_urls(session, [r.url for r in releases])
    return ReleasesView(
        releases=[
            ReleaseCard(
                title=r.title,
                url=r.url,
                source_id=r.source_id,
                published_at=r.published_at,
                summary=summaries.get(r.url),
            )
            for r in releases
        ],
        diffs=[
            DiffCard(
                source_id=d.source_id,
                from_tag=d.from_tag,
                to_tag=d.to_tag,
                computed_at=d.computed_at,
                summary=dict(d.detail.get("summary", {})),
                sections_changed=list(d.detail.get("sections_changed", []))[:12],
            )
            for d in diffs
        ],
    )


# ── 2. Roadmap & Planned Work ────────────────────────────────────────────────


class RoadmapCard(BaseModel):
    title: str
    description: str | None
    maturity: str
    url: str
    last_seen: datetime


class RoadmapView(BaseModel):
    items: list[RoadmapCard]


@router.get("/roadmap", response_model=RoadmapView)
async def roadmap_view() -> RoadmapView:
    async with SessionLocal() as session:
        items = (
            await session.scalars(
                select(RoadmapItem).order_by(RoadmapItem.maturity, RoadmapItem.title)
            )
        ).all()
    return RoadmapView(
        items=[
            RoadmapCard(
                title=i.title,
                description=i.description,
                maturity=str(i.maturity.value if hasattr(i.maturity, "value") else i.maturity),
                url=i.anchor_url or i.source_url,
                last_seen=i.last_seen,
            )
            for i in items
        ]
    )


# ── 3. Open Issues & Feature Requests ────────────────────────────────────────


class GithubItemCard(BaseModel):
    kind: Literal["issue", "pull_request", "discussion"]
    repo: str
    number: int
    title: str
    state: str
    url: str
    updated_at: datetime | None
    last_seen: datetime
    summary: EntityDigest | None = None  # cached S2 structured summary


class IssuesView(BaseModel):
    issues: list[GithubItemCard]
    pull_requests: list[GithubItemCard]


def _card(
    kind: Literal["issue", "pull_request", "discussion"],
    item: Any,
    summaries: dict[str, EntityDigest],
) -> GithubItemCard:
    return GithubItemCard(
        kind=kind,
        repo=item.repo,
        number=item.number,
        title=item.title,
        state=item.state,
        url=item.url,
        updated_at=item.updated_at,
        last_seen=item.last_seen,
        summary=summaries.get(item.url),
    )


@router.get("/issues", response_model=IssuesView)
async def issues_view(limit: int = Query(default=50, ge=1, le=200)) -> IssuesView:
    async with SessionLocal() as session:
        issues = (
            await session.scalars(
                select(Issue)
                .where(Issue.state == "open")
                .order_by(Issue.updated_at.desc().nulls_last())
                .limit(limit)
            )
        ).all()
        pulls = (
            await session.scalars(
                select(PullRequest)
                .where(PullRequest.state == "open")
                .order_by(PullRequest.updated_at.desc().nulls_last())
                .limit(limit)
            )
        ).all()
        summaries = await summaries_for_urls(
            session, [i.url for i in issues] + [p.url for p in pulls]
        )
    return IssuesView(
        issues=[_card("issue", i, summaries) for i in issues],
        pull_requests=[_card("pull_request", p, summaries) for p in pulls],
    )


# ── 4. Current Activity ─────────────────────────────────────────────────────


class ActivityItem(BaseModel):
    kind: Literal["issue", "pull_request", "discussion", "release"]
    title: str
    url: str
    timestamp: datetime
    tier: str  # community for GitHub activity, roadmap for releases


class ActivityView(BaseModel):
    items: list[ActivityItem]


@router.get("/activity", response_model=ActivityView)
async def activity_view(limit: int = Query(default=30, ge=1, le=100)) -> ActivityView:
    items: list[ActivityItem] = []
    async with SessionLocal() as session:
        for kind, model in (
            ("issue", Issue),
            ("pull_request", PullRequest),
            ("discussion", Discussion),
        ):
            rows = (
                await session.scalars(
                    select(model).order_by(model.updated_at.desc().nulls_last()).limit(limit)
                )
            ).all()
            for row in rows:
                items.append(
                    ActivityItem(
                        kind=kind,
                        title=f"{row.title} (#{row.number})",
                        url=row.url,
                        timestamp=row.updated_at or row.last_seen,
                        tier="community",
                    )
                )
        releases = (
            await session.scalars(
                select(Release).order_by(Release.published_at.desc().nulls_last()).limit(10)
            )
        ).all()
        for release in releases:
            if release.published_at is None:
                continue
            items.append(
                ActivityItem(
                    kind="release",
                    title=release.title,
                    url=release.url,
                    timestamp=release.published_at,
                    tier="roadmap",
                )
            )
    items.sort(key=lambda i: i.timestamp, reverse=True)
    return ActivityView(items=items[:limit])
