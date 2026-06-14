"""Version diff: two tags of a local repo → section-level added/changed/removed.
Uses real git (host binary) and the live Postgres for VersionDiff storage."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.collectors.git import collect_git
from app.collectors.registry import SourceSpec
from app.models.entities import VersionDiff
from app.models.source import FetchMethod, Tier
from app.services.version_diff import compute_version_diff

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test"

V1 = """# Spec

## Stable section

Same content.

## Changing section

Old wording.

## Doomed section

Will be removed.
"""

V2 = """# Spec

## Stable section

Same content.

## Changing section

New wording.

## Fresh section

Brand new.
"""


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@pytest.fixture
async def pg_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM version_diffs LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip, not fail
        await engine.dispose()
        pytest.skip("Postgres not reachable or not migrated")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.execute(delete(VersionDiff).where(VersionDiff.source_id == "diff_test"))
        await session.commit()
    await engine.dispose()


async def test_version_diff_sections(pg_session: AsyncSession, tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-b", "main", cwd=origin)
    (origin / "docs").mkdir()
    (origin / "docs" / "spec.md").write_text(V1)
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "v1", cwd=origin)
    _git("tag", "v1.0.0", cwd=origin)
    (origin / "docs" / "spec.md").write_text(V2)
    (origin / "docs" / "new-doc.md").write_text("# New doc\n\nHello.\n")
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "v2", cwd=origin)
    _git("tag", "v2.0.0", cwd=origin)

    spec = SourceSpec(
        id="diff_test", title="t", tier=Tier.reference, method=FetchMethod.git,
        url=str(origin),
    )
    await collect_git(spec, tmp_path / "mirrors")
    mirror = tmp_path / "mirrors" / "diff_test"

    diff = await compute_version_diff(
        pg_session, source_id="diff_test", mirror=mirror, from_tag="v1.0.0", to_tag="v2.0.0"
    )
    await pg_session.commit()
    detail = diff.detail

    assert detail["files_added"] == ["docs/new-doc.md"]
    assert detail["files_removed"] == []
    changed = {(d["file"], d["section"]) for d in detail["sections_changed"]}
    added = {(d["file"], d["section"]) for d in detail["sections_added"]}
    removed = {(d["file"], d["section"]) for d in detail["sections_removed"]}
    assert ("docs/spec.md", "Spec > Changing section") in changed
    assert ("docs/spec.md", "Spec > Fresh section") in added
    assert ("docs/spec.md", "Spec > Doomed section") in removed
    assert ("docs/spec.md", "Spec > Stable section") not in changed

    # idempotent: second call returns the stored row, no new computation
    again = await compute_version_diff(
        pg_session, source_id="diff_test", mirror=mirror, from_tag="v1.0.0", to_tag="v2.0.0"
    )
    assert again.id == diff.id
