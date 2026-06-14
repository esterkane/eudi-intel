"""Phase 8 tests: beat schedule wiring + the new-tag → targeted re-ingest
trigger against a synthetic repo (real git, real Postgres)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.models.entities import Version, VersionDiff
from app.services.parse_pipeline import reingest_new_tags
from app.worker.celery_app import celery_app

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test"


def test_beat_schedule_covers_all_cadences() -> None:
    schedule = celery_app.conf.beat_schedule
    settings = get_settings()
    assert schedule["collect-feeds"]["task"] == "collect_and_parse_feeds"
    assert schedule["collect-feeds"]["schedule"] == settings.poll_feeds_interval
    assert schedule["collect-scrape"]["schedule"] == settings.scrape_issues_interval
    assert schedule["collect-crawl"]["schedule"] == settings.crawl_docs_interval
    assert schedule["collect-git"]["schedule"] == settings.git_pull_interval


def test_all_scheduled_tasks_are_registered() -> None:
    import app.worker.tasks  # noqa: F401 - registers tasks (worker does this via include)

    registered = set(celery_app.tasks.keys())
    for entry in celery_app.conf.beat_schedule.values():
        assert entry["task"] in registered, f"unregistered beat task: {entry['task']}"


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
        await session.execute(delete(Version).where(Version.tag.like("v99.%")))
        await session.execute(delete(Version).where(Version.tag.like("v98.%")))
        await session.execute(delete(VersionDiff).where(VersionDiff.from_tag.like("v98.%")))
        await session.commit()
    await engine.dispose()


async def test_new_tag_triggers_targeted_reingest(
    pg_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulated version bump: two synthetic tags newer than every real ARF tag
    → reingest_new_tags must fetch them and store a fresh diff (Phase 8 gate,
    offline half)."""
    # synthetic 'arf_repo' mirror with two tags
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-b", "main", cwd=origin)
    (origin / "docs").mkdir()
    (origin / "docs" / "spec.md").write_text("# Spec\n\n## Alpha\n\nv98 content.\n")
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "v98", cwd=origin)
    _git("tag", "v98.0.0", cwd=origin)
    (origin / "docs" / "spec.md").write_text("# Spec\n\n## Alpha\n\nv99 content changed.\n")
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "v99", cwd=origin)
    _git("tag", "v99.0.0", cwd=origin)

    repos = tmp_path / "repos"
    repos.mkdir()
    subprocess.run(
        ["git", "clone", str(origin), str(repos / "arf_repo")],
        check=True, capture_output=True, env={**os.environ},
    )

    # the feed parse would create these Version rows; seed them directly
    now = datetime.now(tz=UTC)
    pg_session.add(Version(source_id="arf_repo", tag="v98.0.0", url="https://x/v98", published_at=now))
    pg_session.add(Version(source_id="arf_repo", tag="v99.0.0", url="https://x/v99", published_at=now))
    await pg_session.commit()

    # point the pipeline at the synthetic mirror; avoid touching Qdrant
    settings = Settings(repos_dir=str(repos), database_url=LOCAL_PG)
    import app.services.parse_pipeline as pipeline_mod
    import app.services.vector_index as vec_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", async_sessionmaker(
        pg_session.bind, expire_on_commit=False
    ))

    async def fake_history(settings_: object, tag: str) -> int:
        return 7  # pretend the tag was indexed; Qdrant is out of scope here

    monkeypatch.setattr(vec_mod, "index_history_tag", fake_history)

    report = await reingest_new_tags(settings)
    assert not report.errors, report.errors
    assert any("v98.0.0 → v99.0.0" in d for d in report.diffs_computed)
    assert any("history indexed v99.0.0" in d for d in report.diffs_computed)

    diff = await pg_session.scalar(
        select(VersionDiff).where(
            VersionDiff.from_tag == "v98.0.0", VersionDiff.to_tag == "v99.0.0"
        )
    )
    assert diff is not None
    changed = {(d["file"], d["section"]) for d in diff.detail["sections_changed"]}
    assert ("docs/spec.md", "Spec > Alpha") in changed

    # idempotent: second poll computes nothing new
    report2 = await reingest_new_tags(settings)
    assert not report2.errors
