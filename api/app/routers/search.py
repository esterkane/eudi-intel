"""Search + autosuggest endpoints (Phase 4). Thin layer over the FastAPI-free
retrieval/suggest services."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.query_expansion import expand_query
from app.services.retrieval import SearchFilters, SearchHit, hybrid_search
from app.services.suggest import Suggestion, suggest

router = APIRouter(tags=["search"])


class GlossaryHit(BaseModel):
    term: str
    definition: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
    glossary: list[GlossaryHit] = []


class SuggestResponse(BaseModel):
    query: str
    suggestions: list[Suggestion]


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(min_length=2, max_length=500),
    tier: str | None = Query(default=None, pattern="^(normative|reference|roadmap|community)$"),
    repo: str | None = Query(default=None, max_length=64),
    version: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=10, ge=1, le=30),
    expand: bool = Query(default=False, description="HyDE query expansion for vague queries"),
) -> SearchResponse:
    settings = get_settings()
    filters = SearchFilters(tier=tier, repo=repo, version=version)
    # Glossary aliases are always applied (cheap, deterministic); HyDE only when asked.
    expansion = await expand_query(q, settings, use_hyde=expand)
    hits = await hybrid_search(q, filters, limit, settings, embed_text=expansion.embed_text)
    return SearchResponse(
        query=q,
        results=hits,
        glossary=[
            GlossaryHit(term=t.term, definition=t.definition) for t in expansion.glossary_terms
        ],
    )


@router.get("/suggest", response_model=SuggestResponse)
async def suggest_endpoint(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=10, ge=1, le=25),
) -> SuggestResponse:
    return SuggestResponse(query=q, suggestions=await suggest(q, limit))
