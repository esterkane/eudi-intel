"""POST /answer — grounded generation over the hybrid-search result set
(hybrid-search skill API shape). Returns the answer alongside the full
evidence set so the UI can show citations next to claims."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.generation import GroundedAnswer, LlmUnavailableError, answer_query
from app.services.retrieval import SearchFilters

router = APIRouter(tags=["answer"])


class AnswerRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    tier: str | None = Field(default=None, pattern="^(normative|reference|roadmap|community)$")
    repo: str | None = Field(default=None, max_length=64)
    version: str | None = Field(default=None, max_length=64)
    max_evidence: int = Field(default=8, ge=1, le=15)


@router.post("/answer", response_model=GroundedAnswer)
async def answer(request: AnswerRequest) -> GroundedAnswer:
    filters = SearchFilters(tier=request.tier, repo=request.repo, version=request.version)
    try:
        return await answer_query(
            request.query, filters, get_settings(), max_evidence=request.max_evidence
        )
    except LlmUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
