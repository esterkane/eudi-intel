"""Phase S1 tests: deep activity ingestion upsert path (live Postgres, canned
HTML — no network). Network/logic split lets ingest_pages run offline."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.deep_ingest as deep
from app.models.entities import Document, Section
from app.services.deep_ingest import WorkItem, ingest_pages

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi"

ISSUE_HTML = """
<html><body><article>
<h1>Verifier rejects presentation with invalid_request</h1>
<p>When my relying party sends an OID4VP request the wallet returns invalid_request.
The client_id_scheme seems to be the problem. Tested on Android.</p>
<p>Comment: confirmed, set client_id_scheme to x509_san_dns.</p>
</article></body></html>
"""


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
    # ingest_pages opens app SessionLocal — point it at localhost for the test
    monkeypatch.setattr(deep, "SessionLocal", maker)
    async with maker() as session:
        yield session
        await session.execute(delete(Document).where(Document.source_id == "deep_test"))
        await session.commit()
    await engine.dispose()


async def test_issue_body_becomes_searchable_document(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="Verifier invalid_request")]

    report = await ingest_pages(work, {url: ISSUE_HTML})
    assert report.documents_created == 1
    assert report.skipped_empty == 0

    doc = await pg.scalar(select(Document).where(Document.url == url))
    assert doc is not None
    assert str(doc.tier) == "community"  # issue content is community tier
    assert doc.title == "Verifier invalid_request"  # list title, not body H1
    n_sections = await pg.scalar(
        select(func.count()).select_from(Section).where(Section.document_id == doc.id)
    )
    assert n_sections and n_sections >= 1
    body = await pg.scalar(
        select(Section.content).where(Section.document_id == doc.id).limit(1)
    )
    assert "invalid_request" in body  # the BODY text is now stored/searchable


async def test_reingest_is_idempotent(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="t")]
    first = await ingest_pages(work, {url: ISSUE_HTML})
    assert first.documents_created == 1
    second = await ingest_pages(work, {url: ISSUE_HTML})
    assert second.documents_created == 0
    assert second.unchanged == 1
    count = await pg.scalar(
        select(func.count()).select_from(Document).where(Document.url == url)
    )
    assert count == 1  # no duplicate


async def test_empty_extraction_skipped(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="t")]
    report = await ingest_pages(work, {url: "<html><body></body></html>"})
    assert report.skipped_empty == 1
    assert report.documents_created == 0


async def test_failed_fetch_reported(pg: AsyncSession) -> None:
    url = f"https://github.com/o/r/issues/{uuid.uuid4().hex[:8]}"
    work = [WorkItem(source_id="deep_test", url=url, title="t")]
    report = await ingest_pages(work, {url: None})
    assert report.errors and "fetch failed" in report.errors[0]
