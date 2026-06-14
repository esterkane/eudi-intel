"""Dashboard endpoint integration tests against live Postgres with seeded
fixtures (skips when infra is down). The async endpoint functions are called
directly so everything stays on one event loop. Every card must carry a source
URL and a timestamp — the 'no card without a source link' rule."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.routers.dashboard as dashboard_mod
from app.models.entities import Issue, Maturity, Release, RoadmapItem, VersionDiff
from app.routers.dashboard import activity_view, issues_view, releases_view, roadmap_view

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test"


@pytest.fixture
async def mark(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    mark = f"dash{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM releases LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip, not fail
        await engine.dispose()
        pytest.skip("Postgres not reachable or not migrated")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dashboard_mod, "SessionLocal", maker)

    now = datetime.now(tz=UTC)
    future = now + timedelta(days=365)  # sorts ahead of real ingested data
    async with maker() as session:
        session.add(
            Release(
                source_id=mark, title=f"Release {mark}",
                url=f"https://github.com/x/{mark}/releases/tag/v9.9.9",
                published_at=future,
            )
        )
        session.add(
            RoadmapItem(
                source_url=f"https://docs.example/{mark}", title=f"Feature {mark}",
                description="d", maturity=Maturity.in_progress,
                anchor_url=f"https://docs.example/{mark}#f", last_seen=now,
            )
        )
        session.add(
            Issue(
                repo=f"x/{mark}", number=1, title=f"Issue {mark}", state="open",
                url=f"https://github.com/x/{mark}/issues/1",
                updated_at=future, last_seen=now,
            )
        )
        session.add(
            VersionDiff(
                source_id=mark, from_tag="v1", to_tag="v2", computed_at=future,
                detail={
                    "summary": {"sections_added": 1, "sections_removed": 0,
                                "sections_changed": 2, "files_added": 0, "files_removed": 0},
                    "sections_changed": [{"file": "a.md", "section": "A > B"}],
                },
            )
        )
        await session.commit()
    yield mark
    async with maker() as session:
        await session.execute(delete(Release).where(Release.source_id == mark))
        await session.execute(delete(RoadmapItem).where(RoadmapItem.title == f"Feature {mark}"))
        await session.execute(delete(Issue).where(Issue.repo == f"x/{mark}"))
        await session.execute(delete(VersionDiff).where(VersionDiff.source_id == mark))
        await session.commit()
    await engine.dispose()


async def test_releases_view(mark: str) -> None:
    body = await releases_view(limit=20)
    assert body.releases[0].title == f"Release {mark}"  # newest first
    assert all(r.url for r in body.releases)
    diff = next(d for d in body.diffs if d.source_id == mark)
    assert diff.summary["sections_changed"] == 2


async def test_roadmap_view(mark: str) -> None:
    body = await roadmap_view()
    item = next(i for i in body.items if i.title == f"Feature {mark}")
    assert item.maturity == "in_progress"
    assert item.url.endswith("#f")  # anchor preferred over page url


async def test_issues_view(mark: str) -> None:
    body = await issues_view(limit=50)
    assert body.issues[0].title == f"Issue {mark}"  # newest update first
    assert all(i.url and i.last_seen for i in body.issues)
    assert all(i.state == "open" for i in body.issues)


async def test_activity_view_sorted_and_linked(mark: str) -> None:
    body = await activity_view(limit=30)
    items = body.items
    assert items, "activity must not be empty with seeded data"
    timestamps = [i.timestamp for i in items]
    assert timestamps == sorted(timestamps, reverse=True)
    assert all(i.url and i.tier for i in items)
    kinds = {i.kind for i in items}
    assert "release" in kinds and "issue" in kinds
