"""Phase 7: grounded authoring (grounded-authoring skill).

Evidence-backed drafting, not autonomous authorship: the caller supplies the
evidence set (chosen from search results); qwen3:8b drafts a structured
document whose sections inherit the citations and version stamps of the chunks
they were derived from. Every draft stores a source_basis audit trail and is
born status='draft' — only the explicit finalize action publishes it.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.entities import GeneratedDraft, Section
from app.services.retrieval import Citation

logger = logging.getLogger(__name__)

DocType = Literal["faq", "playbook", "kb_article"]

_MARKER = re.compile(r"\[(\d+)\]")
_H2 = re.compile(r"^##\s+(.*)$", re.MULTILINE)
# Tiers whose content is non-binding: discussion papers and roadmap/STS
# (explicitly informational, subject to change).
_NON_NORMATIVE_TIERS = {"community", "roadmap"}

_STRUCTURE: dict[str, str] = {
    "faq": (
        "Write an FAQ. Each question is a '## Q: <question>' heading followed by "
        "its answer paragraph(s). Every answer sentence must end with bracketed "
        "evidence markers like [1] or [2][3]."
    ),
    "playbook": (
        "Write a troubleshooting playbook with exactly these '## ' sections: "
        "'## Symptom', '## Diagnosis', '## Steps' (numbered list), '## References'. "
        "Every paragraph and step must end with bracketed evidence markers like [1]."
    ),
    "kb_article": (
        "Write a knowledge-base article: '## Summary' first, then topical '## ' "
        "body sections, then '## References'. Every paragraph must end with "
        "bracketed evidence markers like [1] or [2][3]."
    ),
}

_SYSTEM_PROMPT = """\
You are drafting internal documentation for the EU Digital Identity (EUDI)
ecosystem, strictly from the numbered evidence blocks provided. Hard rules:
1. Use ONLY the provided evidence; no outside facts.
2. Every claim ends with the bracketed marker(s) of its supporting evidence
   block. Example: "The WUA must be revocable [2]." The number refers to the
   evidence block, NOT to requirement IDs mentioned inside the text.
3. Structure the document with '## ' markdown headings as instructed.
4. Note evidence tiers: normative > reference > roadmap > community. Prefer
   normative blocks; never present community or roadmap content as binding.
5. Be precise and concise."""

_RETRY_SUFFIX = (
    "\n\nIMPORTANT: Your previous draft omitted the bracketed evidence markers. "
    "Rewrite the full document, making sure EVERY paragraph ends with markers "
    "like [1] or [2][3] referencing the numbered evidence blocks."
)


class EvidenceItem(BaseModel):
    content: str
    citation: Citation


class DraftSection(BaseModel):
    heading: str
    content: str
    cited_indices: list[int]
    citations: list[Citation]  # inherited from the cited evidence
    non_normative: bool  # leans on community/roadmap (STS) content
    uncited: bool  # contains no valid citation marker — flagged, not asserted


class DraftOut(BaseModel):
    id: int
    doc_type: str
    title: str
    status: str
    created_at: datetime
    finalized_at: datetime | None
    sections: list[DraftSection]
    source_basis: dict[str, Any]


def render_authoring_prompt(doc_type: DocType, topic: str, evidence: list[EvidenceItem]) -> str:
    blocks = []
    for i, item in enumerate(evidence, start=1):
        c = item.citation
        blocks.append(
            f"[{i}] (tier: {c.tier} | doc: {c.doc_title} | section: {c.section_heading} "
            f"| version: {c.version_or_tag or 'n/a'} | last_seen: {c.last_seen})\n{item.content}"
        )
    return (
        "EVIDENCE:\n" + "\n\n".join(blocks) + f"\n\nTASK: {_STRUCTURE[doc_type]}\n"
        f"TOPIC: {topic}"
    )


def parse_draft(markdown: str, evidence: list[EvidenceItem]) -> list[DraftSection]:
    """Split on '## ' headings; each section inherits citations from its valid
    markers. Sections without any valid marker are flagged uncited."""
    matches = list(_H2.finditer(markdown))
    sections: list[DraftSection] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        cited: list[int] = []
        for raw in _MARKER.findall(content):
            index = int(raw)
            if 1 <= index <= len(evidence) and index not in cited:
                cited.append(index)
        citations = [evidence[i - 1].citation for i in cited]
        sections.append(
            DraftSection(
                heading=match.group(1).strip(),
                content=content,
                cited_indices=cited,
                citations=citations,
                non_normative=any(c.tier in _NON_NORMATIVE_TIERS for c in citations),
                uncited=not cited and bool(content),
            )
        )
    return sections


async def _current_section_hash(session: AsyncSession, anchor_url: str) -> str | None:
    """Current content hash of the (first) section at an anchor, for the
    source-basis snapshot and the finalize drift check."""
    content_hash: str | None = await session.scalar(
        select(Section.content_hash)
        .where(Section.anchor_url == anchor_url)
        .order_by(Section.order_index)
        .limit(1)
    )
    return content_hash


async def build_source_basis(
    session: AsyncSession, topic: str, evidence: list[EvidenceItem], settings: Settings
) -> dict[str, Any]:
    items = []
    for item in evidence:
        items.append(
            {
                **item.citation.model_dump(),
                "content_hash": await _current_section_hash(session, item.citation.source_url),
            }
        )
    return {
        "model": settings.gen_model,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "topic": topic,
        "evidence": items,
    }


async def create_draft(
    session: AsyncSession,
    *,
    doc_type: DocType,
    topic: str,
    evidence: list[EvidenceItem],
    settings: Settings,
) -> GeneratedDraft:
    # Imported here so unit tests can patch llm.chat in one place
    from app.services.llm import chat

    prompt = render_authoring_prompt(doc_type, topic, evidence)
    markdown = await chat(_SYSTEM_PROMPT, prompt, settings, max_tokens=1536)
    sections = parse_draft(markdown, evidence)
    if sections and all(s.uncited for s in sections):
        # Small-model flakiness: a fully uncited draft is useless — one
        # corrective retry before flagging.
        logger.warning("draft for %r came back fully uncited; retrying once", topic)
        markdown = await chat(_SYSTEM_PROMPT, prompt + _RETRY_SUFFIX, settings, max_tokens=1536)
        sections = parse_draft(markdown, evidence)
    if any(s.uncited for s in sections):
        logger.warning(
            "draft for topic %r has uncited sections: %s",
            topic,
            [s.heading for s in sections if s.uncited],
        )
    draft = GeneratedDraft(
        doc_type=doc_type,
        title=topic[:512],
        status="draft",
        created_at=datetime.now(tz=UTC),
        sections=[s.model_dump() for s in sections],
        source_basis=await build_source_basis(session, topic, evidence, settings),
    )
    session.add(draft)
    await session.commit()
    return draft


class FinalizeResult(BaseModel):
    draft: DraftOut
    warnings: list[str]


async def finalize_draft(session: AsyncSession, draft: GeneratedDraft) -> list[str]:
    """The explicit human publish action. Re-checks that cited sources have
    not drifted since drafting and warns (does not block) if they have."""
    warnings: list[str] = []
    for item in draft.source_basis.get("evidence", []):
        current = await _current_section_hash(session, item["source_url"])
        recorded = item.get("content_hash")
        if current is None:
            warnings.append(f"source no longer found: {item['source_url']}")
        elif recorded and current != recorded:
            warnings.append(f"source changed since drafting: {item['source_url']}")
    draft.status = "published"
    draft.finalized_at = datetime.now(tz=UTC)
    await session.commit()
    return warnings


def to_draft_out(draft: GeneratedDraft) -> DraftOut:
    return DraftOut(
        id=draft.id,
        doc_type=draft.doc_type,
        title=draft.title,
        status=draft.status,
        created_at=draft.created_at,
        finalized_at=draft.finalized_at,
        sections=[DraftSection.model_validate(s) for s in draft.sections],
        source_basis=draft.source_basis,
    )
