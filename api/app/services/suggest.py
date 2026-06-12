"""Typo-tolerant autosuggest via pg_trgm (hybrid-search skill).

Suggestion dictionary: document titles, section headings, issue titles,
release titles, roadmap item titles — all already in Postgres, served with
trigram similarity plus a prefix boost.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import Float, String, bindparam, func, literal, select

from app.db.session import SessionLocal
from app.models.entities import Document, Issue, Release, RoadmapItem, Section

_MIN_SIMILARITY = 0.15


class Suggestion(BaseModel):
    text: str
    kind: str  # document | section | issue | release | roadmap
    url: str
    similarity: float


async def suggest(query: str, limit: int = 10) -> list[Suggestion]:
    q = bindparam("q", query, type_=String)
    sources = (
        select(
            Document.title.label("text"),
            literal("document").label("kind"),
            Document.url.label("url"),
            func.similarity(Document.title, q).cast(Float).label("sim"),
        ),
        select(
            Section.heading,
            literal("section"),
            Section.anchor_url,
            func.similarity(Section.heading, q).cast(Float),
        ),
        select(
            Issue.title,
            literal("issue"),
            Issue.url,
            func.similarity(Issue.title, q).cast(Float),
        ),
        select(
            Release.title,
            literal("release"),
            Release.url,
            func.similarity(Release.title, q).cast(Float),
        ),
        select(
            RoadmapItem.title,
            literal("roadmap"),
            func.coalesce(RoadmapItem.anchor_url, RoadmapItem.source_url),
            func.similarity(RoadmapItem.title, q).cast(Float),
        ),
    )
    union = sources[0].union_all(*sources[1:]).subquery()
    stmt = (
        select(union.c.text, union.c.kind, union.c.url, union.c.sim)
        .where(union.c.sim > _MIN_SIMILARITY)
        .order_by(union.c.sim.desc())
        .limit(limit * 3)  # overfetch, dedupe below
    )
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).all()

    seen: set[str] = set()
    results: list[Suggestion] = []
    for text, kind, url, sim in rows:
        if text in seen:
            continue
        seen.add(text)
        results.append(Suggestion(text=text, kind=kind, url=url, similarity=round(sim, 4)))
        if len(results) >= limit:
            break
    return results
