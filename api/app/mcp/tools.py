"""MCP tool handlers wrapping the EUDI workbench retrieval core.

These are plain, importable async functions — no FastMCP or HTTP coupling — so
they can be unit-tested directly with fakes for the search service and the
source registry (no live Postgres / Qdrant). ``app/mcp/server.py`` registers
thin FastMCP wrappers that supply the real dependencies.

Every handler is wrapped by :func:`app.mcp.errors.guard`, so it either returns a
structured success payload or a structured error payload — never a raised
exception or a stack trace.

DESIGN INVARIANTS (CLAUDE.md):
- THIN: these adapters validate inputs and call the EXISTING retrieval / registry
  functions. No retrieval, ranking, or business logic lives here.
- READ-ONLY: the authoring / publish plane is human-gated and NOT exposed; no
  tool mutates state.
- PROVENANCE PRESERVED: every result/chunk carries the full citation block
  (doc_title, source_url, tier, version_or_tag, section_heading, last_seen) — the
  same shape the HTTP `/search` endpoint returns.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.collectors.registry import REGISTRY, SourceSpec
from app.core.config import Settings
from app.mcp.errors import ToolBusinessError, ToolValidationError, guard
from app.services.retrieval import (
    SearchFilters,
    SearchHit,
    get_section_hit,
    hybrid_search,
)

MAX_LIMIT = 30
_VALID_TIERS = ("normative", "reference", "roadmap", "community")

# Dependency aliases so the server can inject the real functions and tests can
# inject fakes — the impls never import a concrete client directly.
SearchFn = Callable[..., Awaitable[list[SearchHit]]]
FetchChunkFn = Callable[[int], Awaitable[SearchHit | None]]


def _validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ToolValidationError("`query` must be a non-empty string.")
    stripped = query.strip()
    if len(stripped) > 500:
        raise ToolValidationError(
            "`query` must be at most 500 characters.", details={"length": len(stripped)}
        )
    return stripped


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= MAX_LIMIT):
        raise ToolValidationError(
            f"`limit` must be an integer between 1 and {MAX_LIMIT}.", details={"limit": limit}
        )


def _build_filters(filters: dict[str, Any] | None) -> SearchFilters:
    """Validate the optional filter map and build the existing SearchFilters
    model. Only the three retrieval-supported keys are accepted."""
    if filters is None:
        return SearchFilters()
    if not isinstance(filters, dict):
        raise ToolValidationError("`filters` must be an object when provided.")
    allowed = {"tier", "repo", "version"}
    unknown = set(filters) - allowed
    if unknown:
        raise ToolValidationError(
            f"Unknown filter key(s): {sorted(unknown)}. Allowed: {sorted(allowed)}.",
            details={"unknown": sorted(unknown)},
        )
    tier = filters.get("tier")
    if tier is not None and tier not in _VALID_TIERS:
        raise ToolValidationError(f"`tier` must be one of {_VALID_TIERS}.", details={"tier": tier})
    try:
        return SearchFilters(tier=tier, repo=filters.get("repo"), version=filters.get("version"))
    except ValueError as exc:  # pydantic validation of repo/version types
        raise ToolValidationError("Invalid `filters` values.", details={"error": str(exc)})


@guard("hybrid_search")
async def hybrid_search_impl(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 10,
    settings: Settings,
    search: SearchFn = hybrid_search,
) -> dict[str, Any]:
    """Hybrid retrieval over the EUDI corpus. Returns a structured payload whose
    `results` carry the full citation block (provenance preserved)."""
    query = _validate_query(query)
    _validate_limit(limit)
    search_filters = _build_filters(filters)
    hits = await search(query, search_filters, limit, settings)
    return {
        "query": query,
        "count": len(hits),
        "results": [hit.model_dump() for hit in hits],
    }


@guard("get_chunk")
async def get_chunk_impl(
    chunk_id: int,
    *,
    fetch: FetchChunkFn = get_section_hit,
) -> dict[str, Any]:
    """Fetch a single indexed chunk by its integer id. Unknown id is a business
    error (the request is valid but cannot be satisfied)."""
    if not isinstance(chunk_id, int) or isinstance(chunk_id, bool) or chunk_id < 1:
        raise ToolValidationError(
            "`chunk_id` must be a positive integer.", details={"chunk_id": chunk_id}
        )
    hit = await fetch(chunk_id)
    if hit is None:
        raise ToolBusinessError(
            f"No chunk exists with id {chunk_id}.", details={"chunk_id": chunk_id}
        )
    return {"chunk_id": chunk_id, "chunk": hit.model_dump()}


def _source_entry(spec: SourceSpec) -> dict[str, Any]:
    tier = spec.tier.value if hasattr(spec.tier, "value") else str(spec.tier)
    method = spec.method.value if hasattr(spec.method, "value") else str(spec.method)
    return {
        "id": spec.id,
        "title": spec.title,
        "tier": tier,
        "method": method,
        "url": spec.url,
    }


@guard("list_sources")
async def list_sources_impl(
    *,
    registry: Sequence[SourceSpec] = REGISTRY,
) -> dict[str, Any]:
    """List the canonical EUDI sources with their authority tier and fetch method.
    Static registry data — read-only, no backend round trip."""
    sources = [_source_entry(spec) for spec in registry]
    return {"count": len(sources), "sources": sources}
