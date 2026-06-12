"""Authoring endpoints (Phase 7). Drafts are created as status='draft'; the
ONLY path to status='published' is the explicit finalize action below."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.entities import GeneratedDraft
from app.services.authoring import (
    DocType,
    DraftOut,
    EvidenceItem,
    FinalizeResult,
    create_draft,
    finalize_draft,
    to_draft_out,
)
from app.services.llm import LlmUnavailableError

router = APIRouter(prefix="/author", tags=["author"])


class DraftRequest(BaseModel):
    doc_type: DocType
    topic: str = Field(min_length=3, max_length=300)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=15)


class DraftSummary(BaseModel):
    id: int
    doc_type: str
    title: str
    status: str
    created_at: str
    sections: int


@router.post("/draft", response_model=DraftOut)
async def post_draft(request: DraftRequest) -> DraftOut:
    async with SessionLocal() as session:
        try:
            draft = await create_draft(
                session,
                doc_type=request.doc_type,
                topic=request.topic,
                evidence=request.evidence,
                settings=get_settings(),
            )
        except LlmUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return to_draft_out(draft)


@router.get("/drafts", response_model=list[DraftSummary])
async def list_drafts() -> list[DraftSummary]:
    async with SessionLocal() as session:
        drafts = (
            await session.scalars(
                select(GeneratedDraft).order_by(GeneratedDraft.created_at.desc())
            )
        ).all()
    return [
        DraftSummary(
            id=d.id,
            doc_type=d.doc_type,
            title=d.title,
            status=d.status,
            created_at=d.created_at.isoformat(),
            sections=len(d.sections),
        )
        for d in drafts
    ]


@router.get("/draft/{draft_id}", response_model=DraftOut)
async def get_draft(draft_id: int) -> DraftOut:
    async with SessionLocal() as session:
        draft = await session.get(GeneratedDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
        return to_draft_out(draft)


@router.post("/finalize/{draft_id}", response_model=FinalizeResult)
async def finalize(draft_id: int) -> FinalizeResult:
    """The explicit human publish action — drafts cannot become published any
    other way."""
    async with SessionLocal() as session:
        draft = await session.get(GeneratedDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
        if draft.status == "published":
            raise HTTPException(status_code=409, detail="draft is already published")
        warnings = await finalize_draft(session, draft)
        return FinalizeResult(draft=to_draft_out(draft), warnings=warnings)
