"""Phase S2: structured entity summaries (entity-summarization skill).

For each activity entity (issue / PR / discussion / release) produce a strict,
grounded, cached summary so a dashboard card or search result tells you exactly
what it is about. Generated in the worker, regenerated only when the entity's
source content_hash changes. Status and non_normative are set deterministically
(from the entity + its tier), not left to the model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.entities import (
    Discussion,
    Document,
    EntitySummary,
    GithubItemBase,
    Issue,
    PullRequest,
    Release,
    Section,
)
from app.services.llm import chat

logger = logging.getLogger(__name__)

_CATEGORIES = {"bug", "feature_request", "question", "discussion", "release", "spec_change", "other"}
_MAX_SOURCE_CHARS = 6000
_MIN_SOURCE_CHARS = 40
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = """\
You summarize EU Digital Identity (EUDI) ecosystem activity for a technical
support lead. Read the provided entity content and output a JSON object with
EXACTLY these keys and nothing else (no markdown, no prose around it):
{
  "tl_dr": "<one plain-language sentence>",
  "category": "<bug|feature_request|question|discussion|release|spec_change|other>",
  "components": ["<short component tags, e.g. wallet, verifier, issuer, oid4vp, oid4vci>"],
  "what": "<what is being reported or changed, 2-3 sentences>",
  "why": "<why it matters to integrators, 1-2 sentences; empty string if unknown>",
  "recommended_action": "<what a support lead should tell a partner / do next, one sentence>"
}
Use ONLY the provided content. If there is not enough content to summarize,
return {"tl_dr": "insufficient detail to summarize", "category": "other",
"components": [], "what": "", "why": "", "recommended_action": ""}."""


class LlmSummary(BaseModel):
    tl_dr: str
    category: str
    components: list[str]
    what: str
    why: str
    recommended_action: str


class Candidate(BaseModel):
    entity_type: str
    url: str
    title: str
    status: str  # deterministic, from the entity
    source_text: str
    content_hash: str


class SummarizeReport(BaseModel):
    generated: int = 0
    unchanged: int = 0
    insufficient: int = 0
    errors: list[str] = []


_GITHUB_KINDS: tuple[tuple[str, type[GithubItemBase]], ...] = (
    ("issue", Issue),
    ("pull_request", PullRequest),
    ("discussion", Discussion),
)


async def _document_text(session: AsyncSession, url: str) -> tuple[str, str] | None:
    """(text, content_hash) of the body Document at a URL, or None if absent."""
    doc = await session.scalar(select(Document).where(Document.url == url))
    if doc is None:
        return None
    sections = (
        await session.scalars(
            select(Section.content)
            .where(Section.document_id == doc.id)
            .order_by(Section.order_index)
        )
    ).all()
    text = f"{doc.title}\n\n" + "\n\n".join(sections)
    return text[:_MAX_SOURCE_CHARS], doc.content_hash


async def gather_candidates(
    session: AsyncSession, limit: int, only_urls: set[str] | None = None
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for entity_type, model in _GITHUB_KINDS:
        stmt = select(model).order_by(model.updated_at.desc().nulls_last()).limit(limit)
        if only_urls is not None:
            stmt = stmt.where(model.url.in_(only_urls))
        rows = (await session.scalars(stmt)).all()
        for row in rows:
            doc = await _document_text(session, row.url)
            if doc is None:
                continue  # body not deep-ingested yet (S1) → nothing to summarize
            text, content_hash = doc
            candidates.append(
                Candidate(
                    entity_type=entity_type,
                    url=row.url,
                    title=row.title,
                    status=row.state,
                    source_text=text,
                    content_hash=content_hash,
                )
            )
    rel_stmt = select(Release).order_by(Release.published_at.desc().nulls_last()).limit(limit)
    if only_urls is not None:
        rel_stmt = rel_stmt.where(Release.url.in_(only_urls))
    releases = (await session.scalars(rel_stmt)).all()
    for rel in releases:
        text = f"{rel.title}\n\n{rel.summary or ''}".strip()
        candidates.append(
            Candidate(
                entity_type="release",
                url=rel.url,
                title=rel.title,
                status="published",
                source_text=text[:_MAX_SOURCE_CHARS],
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
            )
        )
    return candidates


def _parse_summary(raw: str) -> LlmSummary | None:
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
        return LlmSummary.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def _insufficient(status: str, non_normative: bool) -> dict[str, object]:
    return {
        "tl_dr": "insufficient detail to summarize",
        "category": "other",
        "components": [],
        "what": "",
        "why": "",
        "status": status,
        "recommended_action": "",
        "non_normative": non_normative,
    }


def _finalize(parsed: LlmSummary, status: str, non_normative: bool) -> dict[str, object]:
    category = parsed.category if parsed.category in _CATEGORIES else "other"
    return {
        "tl_dr": parsed.tl_dr[:300],
        "category": category,
        "components": [c[:40] for c in parsed.components[:8]],
        "what": parsed.what,
        "why": parsed.why,
        "status": status,  # deterministic, not the model's guess
        "recommended_action": parsed.recommended_action,
        "non_normative": non_normative,
    }


async def _generate_summary(candidate: Candidate, settings: Settings) -> dict[str, object]:
    # issue/PR/discussion content is community tier; releases are roadmap — all
    # non-normative (only normative/reference tiers are binding).
    non_normative = True
    if len(candidate.source_text.strip()) < _MIN_SOURCE_CHARS:
        return _insufficient(candidate.status, non_normative)
    user = f"ENTITY TYPE: {candidate.entity_type}\nTITLE: {candidate.title}\n\nCONTENT:\n{candidate.source_text}"
    raw = await chat(_SYSTEM_PROMPT, user, settings, max_tokens=512)
    parsed = _parse_summary(raw)
    if parsed is None:
        raw = await chat(
            _SYSTEM_PROMPT,
            user + "\n\nReturn ONLY the JSON object, no other text.",
            settings,
            max_tokens=512,
        )
        parsed = _parse_summary(raw)
    if parsed is None:
        logger.warning("summary JSON unparseable for %s; storing insufficient stub", candidate.url)
        return _insufficient(candidate.status, non_normative)
    return _finalize(parsed, candidate.status, non_normative)


async def summarize_pending(
    settings: Settings, limit: int = 40, only_urls: set[str] | None = None
) -> SummarizeReport:
    report = SummarizeReport()
    async with SessionLocal() as session:
        candidates = await gather_candidates(session, limit, only_urls)
        existing = {
            s.entity_url: s
            for s in (await session.scalars(select(EntitySummary))).all()
        }
    for candidate in candidates:
        prior = existing.get(candidate.url)
        if prior is not None and prior.source_content_hash == candidate.content_hash:
            report.unchanged += 1
            continue
        try:
            summary = await _generate_summary(candidate, settings)
        except Exception as exc:  # noqa: BLE001 - isolate per-entity failures
            report.errors.append(f"{candidate.url}: {exc}")
            continue
        if summary["tl_dr"] == "insufficient detail to summarize":
            report.insufficient += 1
        else:
            report.generated += 1
        async with SessionLocal() as session:
            row = await session.scalar(
                select(EntitySummary).where(EntitySummary.entity_url == candidate.url)
            )
            now = datetime.now(tz=UTC)
            if row is None:
                session.add(
                    EntitySummary(
                        entity_type=candidate.entity_type,
                        entity_url=candidate.url,
                        source_content_hash=candidate.content_hash,
                        model=settings.gen_model,
                        generated_at=now,
                        summary=summary,
                    )
                )
            else:
                row.source_content_hash = candidate.content_hash
                row.summary = summary
                row.model = settings.gen_model
                row.generated_at = now
            await session.commit()
    return report


async def summaries_for_urls(session: AsyncSession, urls: list[str]) -> dict[str, dict[str, object]]:
    """Cached summaries keyed by entity URL, for the dashboard/search to attach."""
    if not urls:
        return {}
    rows = (
        await session.scalars(
            select(EntitySummary).where(EntitySummary.entity_url.in_(urls))
        )
    ).all()
    return {r.entity_url: dict(r.summary) for r in rows}
