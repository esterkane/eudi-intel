"""Dedupe contract against a real Postgres (run-and-test skill: integration tests
use real services, not mocks). Skips when the compose Postgres isn't reachable
on localhost:5432; the live gate run exercises the same path end-to-end."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.collectors.base import CollectResult
from app.models.source import SourceSnapshot
from app.services.snapshots import record_snapshot

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi"


@pytest.fixture
async def pg_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_PG)
    # Schema is owned by Alembic — never create tables here. Require the
    # migrated table; skip when infra/migrations are absent.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM source_snapshots LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip, not fail
        await engine.dispose()
        pytest.skip(
            "Postgres not reachable or not migrated "
            "(docker compose up -d postgres && alembic upgrade head)"
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        # clean up this test's rows only
        await session.execute(
            delete(SourceSnapshot).where(SourceSnapshot.source_id == "dedupe_test")
        )
        await session.commit()
    await engine.dispose()


def _result(url: str, content: str) -> CollectResult:
    import hashlib

    return CollectResult(
        source_id="dedupe_test",
        url=url,
        status="fetched",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        payload=content,
    )


async def test_rerun_does_not_duplicate(pg_session: AsyncSession) -> None:
    url = f"https://example.org/{uuid.uuid4()}"

    first, created1 = await record_snapshot(pg_session, _result(url, "same content"))
    assert created1 and first is not None

    second, created2 = await record_snapshot(pg_session, _result(url, "same content"))
    assert not created2
    assert second is not None and second.id == first.id
    assert second.last_seen_at >= first.fetched_at

    count = await pg_session.scalar(
        select(func.count(SourceSnapshot.id)).where(SourceSnapshot.url == url)
    )
    assert count == 1


async def test_changed_content_creates_new_snapshot(pg_session: AsyncSession) -> None:
    url = f"https://example.org/{uuid.uuid4()}"

    _, created1 = await record_snapshot(pg_session, _result(url, "v1"))
    _, created2 = await record_snapshot(pg_session, _result(url, "v2"))
    assert created1 and created2

    count = await pg_session.scalar(
        select(func.count(SourceSnapshot.id)).where(SourceSnapshot.url == url)
    )
    assert count == 2
