"""Support console endpoint (Phase S4). One query → a structured triage packet
that composes search, grounded generation, S2 summaries, playbooks and glossary."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.llm import LlmUnavailableError
from app.services.retrieval import SearchFilters
from app.services.support import SupportPacket, triage

router = APIRouter(prefix="/support", tags=["support"])


class TriageRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    tier: str | None = Field(default=None, pattern="^(normative|reference|roadmap|community)$")
    repo: str | None = Field(default=None, max_length=64)
    version: str | None = Field(default=None, max_length=64)
    generate: bool = True  # include the grounded answer (the only live generation)
    expand: bool = False  # HyDE query expansion for vague queries


@router.post("/triage", response_model=SupportPacket)
async def support_triage(request: TriageRequest) -> SupportPacket:
    filters = SearchFilters(tier=request.tier, repo=request.repo, version=request.version)
    try:
        return await triage(
            request.query,
            filters,
            get_settings(),
            generate=request.generate,
            expand=request.expand,
        )
    except LlmUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
