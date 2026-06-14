"""Phase S2 tests: JSON parsing/coercion (offline) + the cached summarize path
and idempotency (live Postgres, LLM patched)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.summarize as summ
from app.core.config import get_settings
from app.models.entities import Document, EntitySummary, Issue, Section
from app.models.source import Tier
from app.services.summarize import (
    Candidate,
    _finalize,
    _insufficient,
    _parse_summary,
    summarize_pending,
)

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test"

VALID_JSON = """Here is the summary:
```json
{"tl_dr": "Verifier rejects OID4VP request due to client_id_scheme",
 "category": "bug", "components": ["verifier", "oid4vp"],
 "what": "A relying party gets invalid_request.", "why": "Blocks integration.",
 "recommended_action": "Set client_id_scheme to x509_san_dns."}
```
"""


def test_parse_summary_from_fenced_json() -> None:
    parsed = _parse_summary(VALID_JSON)
    assert parsed is not None
    assert parsed.category == "bug"
    assert "verifier" in parsed.components


def test_parse_summary_rejects_garbage() -> None:
    assert _parse_summary("I cannot help with that.") is None
    assert _parse_summary('{"tl_dr": "x"}') is None  # missing required keys


def test_finalize_coerces_category_and_overrides_status() -> None:
    parsed = _parse_summary(VALID_JSON)
    assert parsed is not None
    parsed.category = "not_a_category"
    out = _finalize(parsed, status="closed", non_normative=True)
    assert out["category"] == "other"  # unknown → other
    assert out["status"] == "closed"  # deterministic, from the entity
    assert out["non_normative"] is True


def test_insufficient_stub_shape() -> None:
    stub = _insufficient("open", True)
    assert stub["tl_dr"] == "insufficient detail to summarize"
    assert stub["components"] == []


@pytest.fixture
async def pg(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM entity_summaries LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip
        await engine.dispose()
        pytest.skip("Postgres not reachable or migration 0007 not applied")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(summ, "SessionLocal", maker)
    async with maker() as session:
        yield session
        await session.execute(
            delete(EntitySummary).where(EntitySummary.entity_url.like("%summ-test%"))
        )
        await session.execute(delete(Document).where(Document.source_id == "summ_test"))
        await session.execute(delete(Issue).where(Issue.repo == "summ-test/r"))
        await session.commit()
    await engine.dispose()


async def _seed_issue_with_body(session: AsyncSession, url: str) -> None:
    now = datetime.now(tz=UTC)
    session.add(
        Issue(repo="summ-test/r", number=1, title="Verifier invalid_request", state="open",
              url=url, updated_at=now, last_seen=now)
    )
    doc = Document(
        source_id="summ_test", url=url, title="Verifier invalid_request", tier=Tier.community,
        doc_type="html", content_hash="hash-v1", first_seen=now, last_seen=now,
    )
    doc.sections.append(
        Section(order_index=0, heading="(introduction)", section_path="(introduction)",
                anchor_url=url, content="A relying party sends an OID4VP request and the "
                "wallet returns invalid_request. client_id_scheme is the problem.",
                content_hash="c1", token_estimate=20, tier=Tier.community)
    )
    session.add(doc)
    await session.commit()


async def test_summarize_caches_and_is_idempotent(
    pg: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    async def fake_chat(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        calls["n"] += 1
        return VALID_JSON

    monkeypatch.setattr(summ, "chat", fake_chat)
    url = f"https://github.com/summ-test/r/issues/{uuid.uuid4().hex[:8]}"  # contains 'summ-test'
    await _seed_issue_with_body(pg, url)

    # only_urls scopes the run to the seeded entity — the test never touches
    # real production entities in the shared dev DB.
    first = await summarize_pending(get_settings(), limit=50, only_urls={url})
    assert first.generated == 1
    row = await pg.scalar(select(EntitySummary).where(EntitySummary.entity_url == url))
    assert row is not None
    assert row.summary["category"] == "bug"
    assert row.summary["status"] == "open"  # from the Issue, not the model
    assert row.summary["non_normative"] is True
    calls_after_first = calls["n"]

    # nothing changed → no regeneration
    second = await summarize_pending(get_settings(), limit=50, only_urls={url})
    assert second.unchanged == 1
    assert calls["n"] == calls_after_first  # the LLM was not called again


async def test_insufficient_when_body_too_short(
    pg: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_chat(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        raise AssertionError("LLM must not be called for too-short content")

    monkeypatch.setattr(summ, "chat", fake_chat)
    candidate = Candidate(
        entity_type="issue", url="https://x/summ-test/short", title="t",
        status="open", source_text="too short", content_hash="h",
    )
    out = await summ._generate_summary(candidate, get_settings())
    assert out["tl_dr"] == "insufficient detail to summarize"
