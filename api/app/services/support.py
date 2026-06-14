"""Phase S4: the support console (support-console skill).

One query → a structured triage packet: a grounded cited answer (optional, the
only live generation), the most relevant issues/discussions WITH their cached S2
summaries ("has someone already hit this?"), a suggested published playbook, and
the matched glossary terms (to explain the topic). Composes the existing planes;
answer generation runs in parallel with the fast retrieval so the packet assembles
in roughly one generation's time, not the sum.
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.entities import GeneratedDraft
from app.services.generation import GroundedAnswer, answer_query
from app.services.query_expansion import expand_query
from app.services.retrieval import SearchFilters, hybrid_search
from app.services.summarize import summaries_for_urls

# GitHub activity item URLs (issue / PR / discussion bodies from S1).
_ACTIVITY_URL = re.compile(r"/(issues|pull|discussions)/\d+")
_PLAYBOOK_TYPES = ("playbook", "kb_article", "faq")
_PLAYBOOK_MIN_SIMILARITY = 0.1
_RELATED_POOL = 20
_RELATED_LIMIT = 6


class GlossaryHit(BaseModel):
    term: str
    definition: str


class RelatedItem(BaseModel):
    url: str
    title: str
    tier: str
    score: float
    summary: dict[str, object] | None  # cached S2 structured summary


class PlaybookRef(BaseModel):
    id: int
    title: str
    doc_type: str


class SupportPacket(BaseModel):
    query: str
    answer: GroundedAnswer | None
    related: list[RelatedItem]
    playbook: PlaybookRef | None
    glossary: list[GlossaryHit]


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


async def related_activity(
    query: str, filters: SearchFilters, settings: Settings, embed_text: str
) -> list[RelatedItem]:
    """Top issues/PRs/discussions matching the query, each with its S2 summary.
    Reranking is capped to a small candidate set so the fast path stays
    responsive — the CPU cross-encoder is the slow part."""
    hits = await hybrid_search(
        query, filters, _RELATED_POOL, settings, embed_text=embed_text, rerank_limit=12
    )
    best: dict[str, tuple[float, str, str]] = {}  # base_url → (score, title, tier)
    for hit in hits:
        if not _ACTIVITY_URL.search(hit.citation.source_url):
            continue
        base = _strip_fragment(hit.citation.source_url)
        if base not in best or hit.score > best[base][0]:
            best[base] = (hit.score, hit.citation.doc_title, hit.citation.tier)
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:_RELATED_LIMIT]
    async with SessionLocal() as session:
        summaries = await summaries_for_urls(session, [url for url, _ in ranked])
    return [
        RelatedItem(
            url=url, title=title, tier=tier, score=round(score, 4), summary=summaries.get(url)
        )
        for url, (score, title, tier) in ranked
    ]


async def best_playbook(query: str) -> PlaybookRef | None:
    """Most title-similar published playbook/KB/FAQ (pg_trgm), if any clears the floor."""
    async with SessionLocal() as session:
        sim = func.similarity(GeneratedDraft.title, query)
        row = (
            await session.execute(
                select(GeneratedDraft.id, GeneratedDraft.title, GeneratedDraft.doc_type, sim)
                .where(
                    GeneratedDraft.status == "published",
                    GeneratedDraft.doc_type.in_(_PLAYBOOK_TYPES),
                    sim > _PLAYBOOK_MIN_SIMILARITY,
                )
                .order_by(sim.desc())
                .limit(1)
            )
        ).first()
    if row is None:
        return None
    return PlaybookRef(id=row[0], title=row[1], doc_type=row[2])


async def triage(
    query: str,
    filters: SearchFilters,
    settings: Settings,
    *,
    generate: bool = True,
    expand: bool = False,
) -> SupportPacket:
    expansion = await expand_query(query, settings, use_hyde=expand)

    async def maybe_answer() -> GroundedAnswer | None:
        return await answer_query(query, filters, settings) if generate else None

    # Live generation (slow) overlaps the fast retrieval/playbook lookups.
    answer, related, playbook = await asyncio.gather(
        maybe_answer(),
        related_activity(query, filters, settings, expansion.embed_text),
        best_playbook(query),
    )
    return SupportPacket(
        query=query,
        answer=answer,
        related=related,
        playbook=playbook,
        glossary=[
            GlossaryHit(term=t.term, definition=t.definition) for t in expansion.glossary_terms
        ],
    )
