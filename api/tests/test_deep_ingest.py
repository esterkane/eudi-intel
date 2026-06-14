"""Deep activity ingestion tests: the source-agnostic upsert path (live Postgres),
the REST thread builder and JSON list parsers (offline, mocked)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.deep_ingest as deep
from app.models.entities import Document, Section
from app.parsers.github_lists import parse_issue_list_json, parse_pull_list_json
from app.services.deep_ingest import WorkItem, fetch_rest_thread, ingest_pages

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi"

# Readable markdown content (extraction happens in the fetch layer now).
ISSUE_MD = (
    "When my relying party sends an OID4VP request the wallet returns "
    "invalid_request. The client_id_scheme seems to be the problem. Tested on Android.\n\n"
    "---\n\nComment by maintainer:\n\nConfirmed, set client_id_scheme to x509_san_dns."
)


@pytest.fixture
async def pg(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM documents LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip
        await engine.dispose()
        pytest.skip("Postgres not reachable or not migrated")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(deep, "SessionLocal", maker)
    async with maker() as session:
        yield session
        await session.execute(delete(Document).where(Document.source_id == "deep_test"))
        await session.commit()
    await engine.dispose()


async def test_thread_becomes_searchable_document(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="Verifier invalid_request")]

    report = await ingest_pages(work, {url: ISSUE_MD})
    assert report.documents_created == 1 and report.skipped_empty == 0

    doc = await pg.scalar(select(Document).where(Document.url == url))
    assert doc is not None
    assert str(doc.tier) == "community"
    assert doc.title == "Verifier invalid_request"  # list title, not body content
    body = await pg.scalar(
        select(Section.content).where(Section.document_id == doc.id).limit(1)
    )
    assert "invalid_request" in body  # the thread content is stored/searchable
    assert "x509_san_dns" in body  # ...including the comment


async def test_reingest_is_idempotent(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="t")]
    assert (await ingest_pages(work, {url: ISSUE_MD})).documents_created == 1
    second = await ingest_pages(work, {url: ISSUE_MD})
    assert second.documents_created == 0 and second.unchanged == 1
    count = await pg.scalar(select(func.count()).select_from(Document).where(Document.url == url))
    assert count == 1


async def test_changed_content_rebuilds_sections(pg: AsyncSession) -> None:
    """The update path clears+rebuilds sections (async eager-load regression)."""
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="t")]
    await ingest_pages(work, {url: ISSUE_MD})
    richer = ISSUE_MD + "\n\n---\n\nComment by carol:\n\nNew detail about key attestation."
    report = await ingest_pages(work, {url: richer})
    assert report.documents_updated == 1
    contents = (
        await pg.scalars(
            select(Section.content).join(Document, Section.document_id == Document.id)
            .where(Document.url == url)
        )
    ).all()
    assert any("key attestation" in c for c in contents)  # new content present
    count = await pg.scalar(select(func.count()).select_from(Document).where(Document.url == url))
    assert count == 1  # still one document


async def test_short_content_skipped(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    report = await ingest_pages([WorkItem(source_id="deep_test", url=url, title="t")], {url: "tiny"})
    assert report.skipped_empty == 1 and report.documents_created == 0


async def test_failed_fetch_reported(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    report = await ingest_pages([WorkItem(source_id="deep_test", url=url, title="t")], {url: None})
    assert report.errors and "fetch failed" in report.errors[0]


# ── REST thread builder (offline, mocked GitHub API) ─────────────────────────


async def test_fetch_rest_thread_combines_body_and_comments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/705"):
            return httpx.Response(200, json={"body": "Issue body about Android attestation."})
        if request.url.path.endswith("/issues/705/comments"):
            return httpx.Response(
                200,
                json=[
                    {"user": {"login": "alice"}, "body": "First comment."},
                    {"user": {"login": "bob"}, "body": "Second comment."},
                ],
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        md = await fetch_rest_thread(
            client, "https://github.com/eu-digital-identity-wallet/x/issues/705", "tok"
        )
    assert md is not None
    assert "Issue body about Android attestation." in md
    assert "Comment by alice" in md and "First comment." in md
    assert "Comment by bob" in md


async def test_fetch_rest_thread_none_for_discussion() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
        assert await fetch_rest_thread(c, "https://github.com/o/r/discussions/3", "tok") is None


# ── REST JSON list parsers (token-mode collection) ───────────────────────────


def test_parse_issue_list_json_excludes_prs() -> None:
    payload = (
        '[{"number": 10, "title": "Real issue", "state": "open",'
        ' "html_url": "https://github.com/o/r/issues/10", "updated_at": "2026-06-01T00:00:00Z"},'
        ' {"number": 11, "title": "A PR", "state": "open", "pull_request": {},'
        ' "html_url": "https://github.com/o/r/pull/11"}]'
    )
    items = parse_issue_list_json(payload, "o/r")
    assert [i.number for i in items] == [10]  # the PR is excluded
    assert items[0].updated_at is not None


def test_parse_pull_list_json_marks_merged() -> None:
    payload = (
        '[{"number": 20, "title": "Merged PR", "state": "closed",'
        ' "merged_at": "2026-05-01T00:00:00Z", "html_url": "https://github.com/o/r/pull/20"}]'
    )
    items = parse_pull_list_json(payload, "o/r")
    assert items[0].state == "merged"
