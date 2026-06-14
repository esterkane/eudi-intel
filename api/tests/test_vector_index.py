"""Phase 3 unit + integration tests. The BGE-M3 model is never loaded here
(embedding calls are patched / pure helpers are tested directly)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.qdrant import point_id
from app.embeddings.bge_m3 import lexical_weights_to_sparse
from app.models.entities import Document, Section
from app.models.source import Tier
from app.services.vector_index import sections_needing_embedding

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test"


def test_lexical_weights_to_sparse() -> None:
    sparse = lexical_weights_to_sparse({"1012": 0.31, "77": 0.02})
    assert sparse.indices == [1012, 77]
    assert sparse.values == [pytest.approx(0.31), pytest.approx(0.02)]


def test_point_id_stable_and_scoped() -> None:
    a = point_id("latest", "https://x/doc.md#s1", 0)
    assert a == point_id("latest", "https://x/doc.md#s1", 0)  # stable across runs
    assert a != point_id("latest", "https://x/doc.md#s1", 1)
    assert a != point_id("history:v2.9.0", "https://x/doc.md#s1", 0)
    uuid.UUID(a)  # valid UUID for Qdrant


@pytest.fixture
async def pg_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT embedded_hash FROM sections LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip, not fail
        await engine.dispose()
        pytest.skip("Postgres not reachable or migration 0004 not applied")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.execute(delete(Document).where(Document.source_id == "embed_test"))
        await session.commit()
    await engine.dispose()


async def test_sections_needing_embedding_selects_only_stale(pg_session: AsyncSession) -> None:
    now = datetime.now(tz=UTC)
    url = f"https://example.org/{uuid.uuid4()}"
    doc = Document(
        source_id="embed_test", url=url, title="t", tier=Tier.reference,
        doc_type="markdown", content_hash="h", first_seen=now, last_seen=now,
    )

    def make_section(order: int, content_hash: str, embedded: str | None) -> Section:
        return Section(
            order_index=order, heading=f"H{order}", section_path=f"H{order}",
            anchor_url=f"{url}#h{order}", content="text", content_hash=content_hash,
            token_estimate=1, tier=Tier.reference, embedded_hash=embedded,
        )

    doc.sections.append(make_section(0, "aaa", None))      # never embedded → pending
    doc.sections.append(make_section(1, "bbb", "bbb"))     # up to date → skip
    doc.sections.append(make_section(2, "ccc", "old"))     # stale → pending
    pg_session.add(doc)
    await pg_session.commit()

    pending = await sections_needing_embedding(pg_session)
    ours = [(s.order_index) for s, d in pending if d.source_id == "embed_test"]
    assert ours == [0, 2]
