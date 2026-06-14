"""FTS + pg_trgm integration against live Postgres (run-and-test skill: real
services for integration). Inserts its own fixture rows; skips if infra or
migration 0005 is absent."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.session as db_session
from app.models.entities import Document, Section
from app.models.source import Tier
from app.services.retrieval import SearchFilters, lexical_search
from app.services.suggest import suggest

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test"

MARKER = f"zebraflux{uuid.uuid4().hex[:8]}"  # collision-proof distinctive token


@pytest.fixture
async def seeded_pg(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT similarity('a', 'a')"))  # pg_trgm present?
    except Exception:  # noqa: BLE001 - infra absent → skip, not fail
        await engine.dispose()
        pytest.skip("Postgres not reachable or pg_trgm migration not applied")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    # retrieval/suggest use app SessionLocal — point it at localhost for the test
    monkeypatch.setattr(db_session, "SessionLocal", maker)
    import app.services.retrieval as retrieval_mod
    import app.services.suggest as suggest_mod

    monkeypatch.setattr(retrieval_mod, "SessionLocal", maker)
    monkeypatch.setattr(suggest_mod, "SessionLocal", maker)

    now = datetime.now(tz=UTC)
    url = f"https://example.org/{MARKER}"
    doc = Document(
        source_id="search_test", url=url, title=f"Quantum Onboarding Spec {MARKER}",
        tier=Tier.reference, doc_type="markdown", content_hash="h",
        first_seen=now, last_seen=now,
    )
    doc.sections.append(
        Section(
            order_index=0, heading=f"Credential revocation with {MARKER}",
            section_path=f"Spec > Credential revocation with {MARKER}",
            anchor_url=f"{url}#revocation", content=f"The {MARKER} flow revokes credentials.",
            content_hash="c1", token_estimate=8, tier=Tier.reference,
        )
    )
    async with maker() as session:
        session.add(doc)
        await session.commit()
    yield MARKER
    async with maker() as session:
        await session.execute(delete(Document).where(Document.source_id == "search_test"))
        await session.commit()
    await engine.dispose()


async def test_lexical_search_finds_exact_term(seeded_pg: str) -> None:
    hits = await lexical_search(f"credential revocation {seeded_pg}", SearchFilters(), 10)
    assert hits, "FTS returned nothing for an indexed term"
    top = hits[0]
    assert seeded_pg in top.content
    assert top.citation.tier == "reference"
    assert top.citation.source_url.endswith("#revocation")


async def test_lexical_search_respects_tier_filter(seeded_pg: str) -> None:
    hits = await lexical_search(
        f"credential revocation {seeded_pg}", SearchFilters(tier="normative"), 10
    )
    assert all(h.citation.tier == "normative" for h in hits)


async def test_heading_search_finds_exact_section_name(seeded_pg: str) -> None:
    from app.services.retrieval import heading_search

    hits = await heading_search(f"Credential revocation with {seeded_pg}", SearchFilters(), 10)
    assert hits and seeded_pg in hits[0].citation.section_heading


async def test_suggest_tolerates_typos(seeded_pg: str) -> None:
    # "Quantum Onboarding Spec" with typos
    results = await suggest("quantm onbording spec", limit=10)
    texts = [r.text for r in results]
    assert any(seeded_pg in t for t in texts), f"typo suggest missed fixture: {texts}"
