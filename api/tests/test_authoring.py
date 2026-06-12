"""Phase 7 tests: citation inheritance, non-normative labeling, uncited flags
(offline) + the publish gate against live Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.entities import GeneratedDraft
from app.services.authoring import (
    EvidenceItem,
    create_draft,
    finalize_draft,
    parse_draft,
    render_authoring_prompt,
)
from app.services.retrieval import Citation

LOCAL_PG = "postgresql+asyncpg://eudi:eudi@localhost:5432/eudi"


def _evidence(n: int, tier: str = "normative") -> EvidenceItem:
    return EvidenceItem(
        content=f"evidence content {n}",
        citation=Citation(
            doc_title=f"Doc {n}",
            source_url=f"https://x/doc{n}#s{n}",
            tier=tier,
            version_or_tag="v2.9.0",
            section_heading=f"Heading {n}",
            last_seen="2026-06-12T00:00:00+00:00",
        ),
    )


DRAFT_MD = """\
Intro line that belongs to no section.

## Q: What is the Wallet Unit Attestation?

It is an attestation issued to a wallet unit [1]. It must be revocable [2].

## Q: Is the community guidance binding?

No, current guidance is a discussion paper [3].

## Q: Anything else?

This paragraph asserts something with no marker at all.
"""


def test_sections_inherit_citations_and_stamps() -> None:
    evidence = [_evidence(1), _evidence(2), _evidence(3, tier="community")]
    sections = parse_draft(DRAFT_MD, evidence)
    assert len(sections) == 3

    first = sections[0]
    assert first.cited_indices == [1, 2]
    assert [c.doc_title for c in first.citations] == ["Doc 1", "Doc 2"]
    assert all(c.version_or_tag == "v2.9.0" for c in first.citations)  # version stamps
    assert not first.non_normative and not first.uncited

    second = sections[1]
    assert second.cited_indices == [3]
    assert second.non_normative  # leans on community content

    third = sections[2]
    assert third.uncited and third.citations == []


def test_markers_beyond_evidence_are_not_inherited() -> None:
    sections = parse_draft("## A\n\nclaim [1] and bogus [9].\n", [_evidence(1)])
    assert sections[0].cited_indices == [1]


def test_prompt_carries_structure_and_metadata() -> None:
    prompt = render_authoring_prompt("playbook", "revocation troubleshooting", [_evidence(1)])
    assert "## Symptom" in prompt
    assert "tier: normative" in prompt and "last_seen" in prompt
    assert "TOPIC: revocation troubleshooting" in prompt


@pytest.fixture
async def pg(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_PG)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM generated_drafts LIMIT 1"))
    except Exception:  # noqa: BLE001 - infra absent → skip, not fail
        await engine.dispose()
        pytest.skip("Postgres not reachable or migration 0006 not applied")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.execute(
            delete(GeneratedDraft).where(GeneratedDraft.title.like("authoring-test-%"))
        )
        await session.commit()
    await engine.dispose()


async def test_publish_requires_explicit_finalize(
    pg: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Phase 7 gate, at service level: born draft, published only by the
    explicit finalize action; finalize warns about missing/drifted sources."""

    async def fake_chat(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        return "## Summary\n\nGrounded summary [1].\n\n## References\n\nSee [1]."

    import app.services.llm as llm_mod

    monkeypatch.setattr(llm_mod, "chat", fake_chat)

    topic = f"authoring-test-{uuid.uuid4().hex[:8]}"
    draft = await create_draft(
        pg,
        doc_type="kb_article",
        topic=topic,
        evidence=[_evidence(1)],
        settings=get_settings(),
    )
    assert draft.status == "draft"  # NEVER born published
    assert draft.finalized_at is None
    assert draft.source_basis["evidence"][0]["tier"] == "normative"
    assert draft.source_basis["model"] == get_settings().gen_model
    assert draft.sections[0]["citations"][0]["doc_title"] == "Doc 1"

    warnings = await finalize_draft(pg, draft)
    assert draft.status == "published"
    assert draft.finalized_at is not None
    # the fixture's fake anchor does not exist in the corpus → drift warning
    assert any("no longer found" in w for w in warnings)


async def test_fully_uncited_draft_retries_once(
    pg: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_chat(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        calls.append(user)
        if len(calls) == 1:
            return "## Summary\n\nNo markers here at all."
        return "## Summary\n\nNow with marker [1]."

    import app.services.llm as llm_mod

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    topic = f"authoring-test-{uuid.uuid4().hex[:8]}"
    draft = await create_draft(
        pg, doc_type="kb_article", topic=topic, evidence=[_evidence(1)],
        settings=get_settings(),
    )
    assert len(calls) == 2
    assert "previous draft omitted" in calls[1]
    assert draft.sections[0]["cited_indices"] == [1]


def test_non_normative_tiers_include_roadmap() -> None:
    sections = parse_draft("## A\n\nclaim [1].\n", [_evidence(1, tier="roadmap")])
    assert sections[0].non_normative is True
