"""Query plane (hybrid-search skill): lexical + dense + sparse → RRF → rerank
→ exact-heading boost → tier-aware ordering → citation blocks. Plain async
functions, no FastAPI coupling. Search is hybrid by design — never vector-only.
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel
from qdrant_client import models as qmodels
from sqlalchemy import Select, func, select

from app.core.config import Settings
from app.db.qdrant import get_qdrant, point_id
from app.db.session import SessionLocal
from app.embeddings.bge_m3 import get_embedder
from app.embeddings.reranker import get_reranker
from app.models.entities import Document, Section

RRF_K = 60
_PER_CHANNEL_LIMIT = 30
# Authority order for close-score tie-breaking: never let community content
# outrank normative on comparable relevance.
_TIER_RANK = {"normative": 0, "reference": 1, "roadmap": 2, "community": 3}
_TIE_EPSILON = 0.05


class Citation(BaseModel):
    doc_title: str
    source_url: str
    tier: str
    version_or_tag: str | None
    section_heading: str
    last_seen: str


class SearchHit(BaseModel):
    score: float
    content: str
    section_path: str
    citation: Citation


class Candidate(BaseModel):
    key: str  # qdrant point id in the latest index
    content: str
    section_path: str
    citation: Citation


class SearchFilters(BaseModel):
    tier: str | None = None
    repo: str | None = None
    version: str | None = None


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def heading_match_bonus(query: str, heading: str) -> float:
    """Exact spec/section-name queries must surface their section first
    (hybrid-search skill: lexical wins on exact identifiers). A normalized
    containment match earns a bonus that lifts the hit above prose-relevance
    scores, which are bounded by 1."""
    nq, nh = _normalize(query), _normalize(heading)
    if not nq or not nh:
        return 0.0
    if nq == nh or nq in nh or nh in nq:
        return 2.0
    return 0.0


def rrf_fuse(ranked_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion: score(key) = Σ 1/(k + rank)."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, key in enumerate(ranked):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return scores


def tier_aware_order(scored: list[tuple[float, Candidate]]) -> list[tuple[float, Candidate]]:
    """Sort by score; candidates within _TIE_EPSILON of a group's leader count
    as tied and are ordered by authority tier (normative first)."""
    by_score = sorted(scored, key=lambda item: -item[0])
    ordered: list[tuple[float, Candidate]] = []
    group: list[tuple[float, Candidate]] = []
    for item in by_score:
        if group and group[0][0] - item[0] > _TIE_EPSILON:
            group.sort(key=lambda it: (_TIER_RANK.get(it[1].citation.tier, 9), -it[0]))
            ordered.extend(group)
            group = []
        group.append(item)
    group.sort(key=lambda it: (_TIER_RANK.get(it[1].citation.tier, 9), -it[0]))
    ordered.extend(group)
    return ordered


def _candidate_from_section(section: Section, document: Document) -> Candidate:
    tier = document.tier.value if hasattr(document.tier, "value") else str(document.tier)
    return Candidate(
        key=point_id("latest", section.anchor_url, section.order_index),
        content=section.content,
        section_path=section.section_path,
        citation=Citation(
            doc_title=document.title,
            source_url=section.anchor_url,
            tier=tier,
            version_or_tag=document.version_or_tag,
            section_heading=section.heading,
            last_seen=document.last_seen.isoformat(),
        ),
    )


def _candidate_from_payload(key: str, payload: dict[str, object]) -> Candidate:
    return Candidate(
        key=key,
        content=str(payload["content"]),
        section_path=str(payload["section_path"]),
        citation=Citation(
            doc_title=str(payload["doc_title"]),
            source_url=str(payload["source_url"]),
            tier=str(payload["tier"]),
            version_or_tag=(
                str(payload["version_or_tag"]) if payload.get("version_or_tag") else None
            ),
            section_heading=str(payload["section_heading"]),
            last_seen=str(payload["last_seen"]),
        ),
    )


def _apply_lexical_filters(stmt: Select[tuple[Section, Document]], filters: SearchFilters) -> Select[tuple[Section, Document]]:
    if filters.tier:
        stmt = stmt.where(Section.tier == filters.tier)
    if filters.repo:
        stmt = stmt.where(Document.source_id == filters.repo)
    if filters.version:
        stmt = stmt.where(Document.version_or_tag == filters.version)
    return stmt


async def lexical_search(query: str, filters: SearchFilters, limit: int) -> list[Candidate]:
    tsvector = func.to_tsvector("english", Section.heading + " " + Section.content)
    tsquery = func.websearch_to_tsquery("english", query)
    stmt = (
        select(Section, Document)
        .join(Document, Section.document_id == Document.id)
        .where(tsvector.op("@@")(tsquery))
        .order_by(func.ts_rank(tsvector, tsquery).desc())
        .limit(limit)
    )
    stmt = _apply_lexical_filters(stmt, filters)
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).all()
    return [_candidate_from_section(section, document) for section, document in rows]


_HEADING_SIMILARITY_FLOOR = 0.25


async def heading_search(query: str, filters: SearchFilters, limit: int) -> list[Candidate]:
    """Dedicated heading channel (pg_trgm): exact spec/section-name queries must
    reach the candidate set even when content-level ranking buries them."""
    sim = func.similarity(Section.heading, query)
    stmt = (
        select(Section, Document)
        .join(Document, Section.document_id == Document.id)
        .where(sim > _HEADING_SIMILARITY_FLOOR)
        .order_by(sim.desc())
        .limit(limit)
    )
    stmt = _apply_lexical_filters(stmt, filters)
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).all()
    return [_candidate_from_section(section, document) for section, document in rows]


def _qdrant_filter(filters: SearchFilters) -> qmodels.Filter | None:
    conditions: list[qmodels.Condition] = []
    if filters.tier:
        conditions.append(
            qmodels.FieldCondition(key="tier", match=qmodels.MatchValue(value=filters.tier))
        )
    if filters.repo:
        conditions.append(
            qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=filters.repo))
        )
    if filters.version:
        conditions.append(
            qmodels.FieldCondition(
                key="version_or_tag", match=qmodels.MatchValue(value=filters.version)
            )
        )
    return qmodels.Filter(must=conditions) if conditions else None


async def vector_search(
    query: str,
    filters: SearchFilters,
    limit: int,
    settings: Settings,
    embed_text: str | None = None,
) -> tuple[list[Candidate], list[Candidate]]:
    """Dense and sparse result lists from one query embedding. `embed_text`
    (when given, from query expansion) is embedded instead of the raw query —
    the semantic-recall lever — while lexical channels keep the original query."""
    # CPU-bound torch call — keep it off the event loop so concurrent
    # requests (e.g. autosuggest while a search runs) stay responsive.
    embedded = (await asyncio.to_thread(get_embedder().embed, [embed_text or query]))[0]
    client = get_qdrant()
    qfilter = _qdrant_filter(filters)
    dense_res = await client.query_points(
        collection_name=settings.qdrant_latest_collection,
        query=embedded.dense,
        using="dense",
        query_filter=qfilter,
        limit=limit,
    )
    sparse_res = await client.query_points(
        collection_name=settings.qdrant_latest_collection,
        query=qmodels.SparseVector(
            indices=embedded.sparse.indices, values=embedded.sparse.values
        ),
        using="sparse",
        query_filter=qfilter,
        limit=limit,
    )
    dense = [
        _candidate_from_payload(str(p.id), p.payload or {}) for p in dense_res.points
    ]
    sparse = [
        _candidate_from_payload(str(p.id), p.payload or {}) for p in sparse_res.points
    ]
    return dense, sparse


async def hybrid_search(
    query: str,
    filters: SearchFilters,
    limit: int,
    settings: Settings,
    embed_text: str | None = None,
) -> list[SearchHit]:
    lexical = await lexical_search(query, filters, _PER_CHANNEL_LIMIT)
    headings = await heading_search(query, filters, 10)
    dense, sparse = await vector_search(
        query, filters, _PER_CHANNEL_LIMIT, settings, embed_text=embed_text
    )

    candidates: dict[str, Candidate] = {}
    for channel in (headings, lexical, dense, sparse):
        for candidate in channel:
            candidates.setdefault(candidate.key, candidate)

    fused = rrf_fuse(
        [
            [c.key for c in lexical],
            [c.key for c in headings],
            [c.key for c in dense],
            [c.key for c in sparse],
        ]
    )
    top_keys = sorted(fused, key=lambda k: fused[k], reverse=True)
    top_keys = top_keys[: settings.rerank_candidates]

    if settings.rerank_enabled and top_keys:
        contents = [candidates[k].content for k in top_keys]
        # CPU-bound cross-encoder — off the event loop (see vector_search)
        rerank_scores = await asyncio.to_thread(get_reranker().score, query, contents)
        scored = [(score, candidates[key]) for key, score in zip(top_keys, rerank_scores)]
    else:
        scored = [(fused[key], candidates[key]) for key in top_keys]

    scored = [
        (score + heading_match_bonus(query, candidate.citation.section_heading), candidate)
        for score, candidate in scored
    ]
    ordered = tier_aware_order(scored)
    return [
        SearchHit(
            score=round(score, 6),
            content=candidate.content,
            section_path=candidate.section_path,
            citation=candidate.citation,
        )
        for score, candidate in ordered[:limit]
    ]
